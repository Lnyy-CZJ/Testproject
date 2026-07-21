package service

import (
	"bug-agent/internal/ai"
	"bug-agent/internal/model"
	"bug-agent/testutil"
	"context"
	"fmt"
	"strings"
	"testing"
)

type stubDraftAIClient struct {
	response string
	err      error
}

func (s *stubDraftAIClient) Chat(ctx context.Context, req *ai.ChatRequest) (*ai.ChatResponse, error) {
	if s.err != nil {
		return nil, s.err
	}
	return &ai.ChatResponse{
		Choices: []ai.Choice{{
			Message: ai.Message{Content: s.response},
		}},
		Usage: ai.Usage{PromptTokens: 128, CompletionTokens: 64, TotalTokens: 192},
	}, nil
}

func (s *stubDraftAIClient) ChatStream(ctx context.Context, req *ai.ChatRequest) (<-chan *ai.StreamChunk, error) {
	return nil, fmt.Errorf("not implemented")
}

func TestDefectDraftService_GenerateDraft_UsesAIResponseWhenAvailable(t *testing.T) {
	db := testutil.SetupTestDB(t)
	project := testutil.CreateTestProject(t, db, "Draft AI Project", "DAIP")
	iteration := model.Iteration{ProjectID: project.ID, Name: "Sprint Chat", Status: "active"}
	if err := db.Create(&iteration).Error; err != nil {
		t.Fatalf("create iteration failed: %v", err)
	}
	config := model.ProjectAIConfig{ProjectID: project.ID, Provider: "mock-fail", ModelName: "draft-model", IsDefault: true}
	if err := db.Create(&config).Error; err != nil {
		t.Fatalf("create ai config failed: %v", err)
	}

	svc := NewDefectDraftService(db)
	svc.newClient = func(cfg model.ProjectAIConfig) (ai.AIClient, error) {
		return &stubDraftAIClient{response: `{"title":"登录按钮被键盘遮挡","descriptionMarkdown":"## 现象\n登录页底部按钮在键盘弹起后被遮挡。","severity":"major","priority":"P1","type":"ui","tags":["login","ios"],"missingInformation":["缺少设备型号"],"suggestedIterationId":` + fmt.Sprintf("%d", iteration.ID) + `,"confidence":0.91}`}, nil
	}

	draft, err := svc.GenerateDraft(context.Background(), project.ID, DefectDraftRequest{Message: "iOS 登录页按钮被键盘挡住了"})
	if err != nil {
		t.Fatalf("GenerateDraft failed: %v", err)
	}
	if draft.Title != "登录按钮被键盘遮挡" {
		t.Fatalf("unexpected title: %s", draft.Title)
	}
	if draft.Type != model.DefectTypeUI {
		t.Fatalf("expected ui type, got %s", draft.Type)
	}
	if draft.Priority != model.PriorityP1 {
		t.Fatalf("expected P1, got %s", draft.Priority)
	}
	if draft.SuggestedIterationID == nil || *draft.SuggestedIterationID != iteration.ID {
		t.Fatalf("unexpected suggested iteration: %+v", draft.SuggestedIterationID)
	}
	if draft.SourceMode != model.IssueSourceManualChat {
		t.Fatalf("expected manual chat source mode, got %s", draft.SourceMode)
	}
	if draft.Provider != "mock-fail" || draft.ModelName != "draft-model" {
		t.Fatalf("expected ai metadata, got %+v", draft)
	}
}

func TestDefectDraftService_GenerateDraft_FallsBackWhenNoAIConfig(t *testing.T) {
	db := testutil.SetupTestDB(t)
	project := testutil.CreateTestProject(t, db, "Draft Fallback Project", "DFBP")
	iteration := model.Iteration{ProjectID: project.ID, Name: "Sprint Active", Status: "active"}
	if err := db.Create(&iteration).Error; err != nil {
		t.Fatalf("create iteration failed: %v", err)
	}

	svc := NewDefectDraftService(db)
	draft, err := svc.GenerateDraft(context.Background(), project.ID, DefectDraftRequest{Message: "登录页按钮被键盘遮挡"})
	if err != nil {
		t.Fatalf("GenerateDraft failed: %v", err)
	}
	if draft.Title == "" {
		t.Fatalf("expected title")
	}
	if draft.Type != model.DefectTypeOther {
		t.Fatalf("expected fallback type other, got %s", draft.Type)
	}
	if draft.Priority != model.PriorityP2 {
		t.Fatalf("expected fallback priority P2, got %s", draft.Priority)
	}
	if draft.SuggestedIterationID == nil || *draft.SuggestedIterationID != iteration.ID {
		t.Fatalf("expected active iteration suggestion, got %+v", draft.SuggestedIterationID)
	}
	if !draft.FallbackUsed {
		t.Fatalf("expected fallback draft")
	}
	if draft.FallbackReason == "" {
		t.Fatalf("expected fallback reason")
	}
}

func TestDefectDraftService_GenerateDraft_FallbackReasonWhenAIRequestTimeout(t *testing.T) {
	db := testutil.SetupTestDB(t)
	project := testutil.CreateTestProject(t, db, "Draft Timeout Project", "DTP")
	config := model.ProjectAIConfig{ProjectID: project.ID, Provider: "mock-fail", ModelName: "draft-model", IsDefault: true}
	if err := db.Create(&config).Error; err != nil {
		t.Fatalf("create ai config failed: %v", err)
	}

	svc := NewDefectDraftService(db)
	svc.newClient = func(cfg model.ProjectAIConfig) (ai.AIClient, error) {
		return &stubDraftAIClient{err: fmt.Errorf("request timeout")}, nil
	}

	draft, err := svc.GenerateDraft(context.Background(), project.ID, DefectDraftRequest{Message: "登录页按钮被键盘遮挡"})
	if err != nil {
		t.Fatalf("GenerateDraft failed: %v", err)
	}
	if !draft.FallbackUsed {
		t.Fatalf("expected fallback draft")
	}
	if draft.FallbackReason == "" {
		t.Fatalf("expected fallback reason")
	}
	if got, want := draft.FallbackReason, "超时"; !strings.Contains(got, want) {
		t.Fatalf("expected fallback reason contains %q, got %q", want, got)
	}
}
