package service

import (
	"bug-agent/internal/model"
	"testing"
)

func TestShouldRecordAITokenUsageRequiresConsumedTokens(t *testing.T) {
	if shouldRecordAITokenUsage(model.AITokenUsage{TotalTokens: 0}) {
		t.Fatal("zero-token records should not be tracked as AI token consumption")
	}
	if !shouldRecordAITokenUsage(model.AITokenUsage{TotalTokens: 1}) {
		t.Fatal("positive token usage should be tracked")
	}
}

func TestEstimateTokenUsageFromTextReturnsNonZeroUsage(t *testing.T) {
	usage := EstimateTokenUsageFromText("分析这个缺陷并定位相关文件", "修复摘要和验证建议")
	if usage.PromptTokens <= 0 {
		t.Fatalf("expected prompt token estimate > 0, got %d", usage.PromptTokens)
	}
	if usage.CompletionTokens <= 0 {
		t.Fatalf("expected completion token estimate > 0, got %d", usage.CompletionTokens)
	}
	if usage.TotalTokens != usage.PromptTokens+usage.CompletionTokens {
		t.Fatalf("expected total to equal prompt + completion, got %#v", usage)
	}
}
