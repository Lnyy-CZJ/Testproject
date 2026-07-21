package ai

import (
	"strings"
	"testing"
)

func TestBuildBackendPrompt_ConstrainsAffectedFilesToRelatedFiles(t *testing.T) {
	prompt := BuildBackendPrompt(map[string]interface{}{
		"DefectCode":        "BUG-1",
		"DefectTitle":       "ProjectRepos 云效仓库导入搜索无效",
		"DefectDescription": "仓库导入页面搜索应本地过滤",
		"Severity":          "high",
		"Priority":          "P1",
		"DefectType":        "functional",
		"RelatedFiles":      []string{"web/src/pages/projects/ProjectRepos.tsx"},
	})

	if !strings.Contains(prompt, "web/src/pages/projects/ProjectRepos.tsx") {
		t.Fatalf("expected prompt to include related files, got: %s", prompt)
	}
	if !strings.Contains(prompt, "affectedFiles 只能从相关文件列表中选择") {
		t.Fatalf("expected prompt to constrain affectedFiles to related files, got: %s", prompt)
	}
	if !strings.Contains(prompt, "repoHint") {
		t.Fatalf("expected prompt to include repoHint contract, got: %s", prompt)
	}
}

func TestBuildFixGenerationPrompt_RequiresStructuredPatchOutput(t *testing.T) {
	prompt := BuildFixGenerationPrompt(`{"rootCause":"timeout"}`, "package main\n", "go", "main.go", "修复超时重试逻辑", "")

	if !strings.Contains(prompt, "只输出JSON") {
		t.Fatalf("expected json-only instruction, got: %s", prompt)
	}
	if !strings.Contains(prompt, "hunks[].oldContent 必须逐字复制当前代码中唯一且连续的一段内容") {
		t.Fatalf("expected exact hunk context instruction, got: %s", prompt)
	}
	if strings.Contains(prompt, "输出完整目标文件内容") {
		t.Fatalf("prompt must not require full target file content, got: %s", prompt)
	}
	if !strings.Contains(prompt, "目标文件: main.go") {
		t.Fatalf("expected prompt to include target file context, got: %s", prompt)
	}
}

func TestBuildFrontendAndUIPrompt_RequireRelatedFiles(t *testing.T) {
	frontendPrompt := BuildFrontendPrompt(map[string]interface{}{
		"DefectCode":        "BUG-2",
		"DefectTitle":       "登录错误提示未显示",
		"DefectDescription": "用户输入错误密码无提示",
		"RelatedFiles":      []string{"web/src/pages/Login.tsx"},
	})
	if !strings.Contains(frontendPrompt, "web/src/pages/Login.tsx") {
		t.Fatalf("expected frontend prompt to include related files, got: %s", frontendPrompt)
	}
	if !strings.Contains(frontendPrompt, "\"filePath\": \"真实路径\"") {
		t.Fatalf("expected frontend prompt to require filePath in steps, got: %s", frontendPrompt)
	}

	uiPrompt := BuildUIPrompt(map[string]interface{}{
		"DefectCode":        "BUG-3",
		"DefectTitle":       "按钮样式异常",
		"DefectDescription": "主要操作按钮颜色未按规范",
		"RelatedFiles":      []string{"web/src/components/Button.tsx"},
	})
	if !strings.Contains(uiPrompt, "web/src/components/Button.tsx") {
		t.Fatalf("expected ui prompt to include related files, got: %s", uiPrompt)
	}
	if !strings.Contains(uiPrompt, "\"filePath\": \"真实路径\"") {
		t.Fatalf("expected ui prompt to require filePath in steps, got: %s", uiPrompt)
	}
}
