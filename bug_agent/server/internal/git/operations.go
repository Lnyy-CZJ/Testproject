package git

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/go-git/go-git/v5"
	"github.com/go-git/go-git/v5/plumbing"
	"github.com/go-git/go-git/v5/plumbing/object"
)

// CreateBranch 创建新分支
func (r *Repository) CreateBranch(baseBranch, newBranch string) error {
	if r.repo == nil {
		return fmt.Errorf("repository not initialized")
	}

	worktree, err := r.repo.Worktree()
	if err != nil {
		return fmt.Errorf("get worktree failed: %w", err)
	}

	branchName := plumbing.NewBranchReferenceName(newBranch)

	// 检查分支是否已存在
	_, err = r.repo.Reference(branchName, false)
	if err == nil {
		// 分支已存在，切换到该分支
		err = worktree.Checkout(&git.CheckoutOptions{
			Branch: branchName,
		})
		if err != nil {
			return fmt.Errorf("checkout existing branch %s failed: %w", newBranch, err)
		}
		return nil
	}

	// 先切换到基础分支
	baseRef := plumbing.NewBranchReferenceName(baseBranch)
	err = worktree.Checkout(&git.CheckoutOptions{
		Branch: baseRef,
	})
	if err != nil {
		// 如果基础分支不存在，使用当前HEAD
	}

	// 切换到新分支
	err = worktree.Checkout(&git.CheckoutOptions{
		Branch: branchName,
		Create: true,
	})
	if err != nil {
		return fmt.Errorf("create and checkout branch %s failed: %w", newBranch, err)
	}

	r.branch = newBranch
	return nil
}

// safePath validates that the resolved path stays under workDir, preventing path traversal.
func safePath(workDir, subPath string) (string, error) {
	absBase, err := filepath.Abs(workDir)
	if err != nil {
		return "", fmt.Errorf("resolve workDir failed: %w", err)
	}
	fullPath := filepath.Join(absBase, filepath.FromSlash(subPath))
	absFull, err := filepath.Abs(fullPath)
	if err != nil {
		return "", fmt.Errorf("resolve path failed: %w", err)
	}
	if !strings.HasPrefix(absFull, absBase+string(filepath.Separator)) && absFull != absBase {
		return "", fmt.Errorf("path %q escapes work directory", subPath)
	}
	return absFull, nil
}

// ModifyFile 修改或创建文件
func (r *Repository) ModifyFile(filePath, content string) error {
	if r.workDir == "" {
		return fmt.Errorf("work directory not set")
	}

	fullPath, err := safePath(r.workDir, filePath)
	if err != nil {
		return err
	}

	// 确保目录存在
	dir := filepath.Dir(fullPath)
	if dir != "" && dir != "." {
		err := os.MkdirAll(dir, 0755)
		if err != nil {
			return fmt.Errorf("create directory failed: %w", err)
		}
	}

	err = os.WriteFile(fullPath, []byte(content), 0644)
	if err != nil {
		return fmt.Errorf("write file failed: %w", err)
	}

	// 暂存修改
	worktree, err := r.repo.Worktree()
	if err != nil {
		return fmt.Errorf("get worktree failed: %w", err)
	}

	_, err = worktree.Add(filePath)
	if err != nil {
		return fmt.Errorf("stage file %s failed: %w", filePath, err)
	}

	return nil
}

// Commit 提交修改
func (r *Repository) Commit(message string) (string, error) {
	if r.repo == nil {
		return "", fmt.Errorf("repository not initialized")
	}

	worktree, err := r.repo.Worktree()
	if err != nil {
		return "", fmt.Errorf("get worktree failed: %w", err)
	}

	hash, err := worktree.Commit(message, &git.CommitOptions{
		Author: &object.Signature{
			Name:  "BugAgent",
			Email: "bug-agent@ai.com",
			When:  time.Now(),
		},
	})
	if err != nil {
		return "", fmt.Errorf("commit failed: %w", err)
	}

	return hash.String()[:7], nil
}

// Push 推送到远程仓库
func (r *Repository) Push(auth *Auth) error {
	if r.repo == nil {
		return fmt.Errorf("repository not initialized")
	}

	pushOpts := &git.PushOptions{}

	if authMethod := buildHTTPAuthMethod(valueOrZero(auth)); authMethod != nil {
		pushOpts.Auth = authMethod
	}

	err := r.repo.Push(pushOpts)
	if err != nil && !strings.Contains(err.Error(), "already up-to-date") {
		return fmt.Errorf("push failed: %w", err)
	}

	return nil
}

func valueOrZero(auth *Auth) Auth {
	if auth == nil {
		return Auth{}
	}
	return *auth
}

// GetCurrentBranch 获取当前分支名
func (r *Repository) GetCurrentBranch() (string, error) {
	if r.repo == nil {
		return "", fmt.Errorf("repository not initialized")
	}

	ref, err := r.repo.Head()
	if err != nil {
		return "", fmt.Errorf("get head failed: %w", err)
	}

	return ref.Name().Short(), nil
}

// GetDiff 获取当前未提交的diff（简化版）
func (r *Repository) GetDiff() (string, error) {
	if r.repo == nil {
		return "", fmt.Errorf("repository not initialized")
	}

	worktree, err := r.repo.Worktree()
	if err != nil {
		return "", fmt.Errorf("get worktree failed: %w", err)
	}

	status, err := worktree.Status()
	if err != nil {
		return "", fmt.Errorf("get status failed: %w", err)
	}

	var diff strings.Builder
	for file, s := range status {
		if s.Staging != git.Unmodified || s.Worktree != git.Unmodified {
			diff.WriteString(fmt.Sprintf("%s: staging=%v worktree=%v\n", file, s.Staging, s.Worktree))
		}
	}

	if diff.Len() == 0 {
		return "", nil
	}

	return diff.String(), nil
}

// CreateFixBranch 创建修复分支（标准命名：fix/BUG-{code}-{序号}）
func (r *Repository) CreateFixBranch(defectCode string, seq int) (string, error) {
	baseBranch := "main" // 默认从main分支创建

	currentBranch, err := r.GetCurrentBranch()
	if err == nil && currentBranch != "" {
		baseBranch = currentBranch
	}

	fixBranch := fmt.Sprintf("fix/BUG-%s-%03d", defectCode, seq)

	err = r.CreateBranch(baseBranch, fixBranch)
	if err != nil {
		return "", fmt.Errorf("create fix branch failed: %w", err)
	}

	return fixBranch, nil
}

// GetStagedFiles 获取暂存的文件列表
func (r *Repository) GetStagedFiles() ([]string, error) {
	if r.repo == nil {
		return nil, fmt.Errorf("repository not initialized")
	}

	worktree, err := r.repo.Worktree()
	if err != nil {
		return nil, fmt.Errorf("get worktree failed: %w", err)
	}

	status, err := worktree.Status()
	if err != nil {
		return nil, fmt.Errorf("get status failed: %w", err)
	}

	var files []string
	for file, s := range status {
		if s.Staging != git.Unmodified {
			files = append(files, file)
		}
	}

	return files, nil
}

// ReadFileContent 读取文件内容（用于备份）
func (r *Repository) ReadFileContent(path string) (string, error) {
	fullPath, err := safePath(r.workDir, path)
	if err != nil {
		return "", err
	}
	content, err := os.ReadFile(fullPath)
	if err != nil {
		return "", fmt.Errorf("read file failed: %w", err)
	}
	return string(content), nil
}

// BackupFile 备份原始文件
func (r *Repository) BackupFile(path string) (string, error) {
	content, err := r.ReadFileContent(path)
	if err != nil {
		// 文件不存在，不需要备份
		return "", nil
	}

	backupPath := path + ".bak." + time.Now().Format("20060102150405")
	err = r.ModifyFile(backupPath, content)
	if err != nil {
		return "", fmt.Errorf("backup file failed: %w", err)
	}

	return backupPath, nil
}

// RestoreFile 从备份恢复文件
func (r *Repository) RestoreFile(path, backupPath string) error {
	content, err := r.ReadFileContent(backupPath)
	if err != nil {
		return fmt.Errorf("read backup file failed: %w", err)
	}

	return r.ModifyFile(path, content)
}

// ListFiles 列出仓库中的所有文件（可选过滤）
func (r *Repository) ListFiles(pattern string) ([]string, error) {
	if r.workDir == "" {
		return nil, fmt.Errorf("work directory not set")
	}

	var files []string

	err := filepath.Walk(r.workDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return nil
		}

		if info.IsDir() {
			if strings.HasPrefix(info.Name(), ".") || info.Name() == "node_modules" {
				return filepath.SkipDir
			}
			return nil
		}

		relPath, _ := filepath.Rel(r.workDir, path)
		relPath = filepath.ToSlash(relPath)
		if strings.HasPrefix(filepath.Base(relPath), ".") {
			return nil
		}

		if pattern == "" || strings.Contains(relPath, pattern) {
			files = append(files, relPath)
		}

		return nil
	})

	return files, err
}

type BuildResult struct {
	Success    bool   `json:"success"`
	Output     string `json:"output"`
	Duration   int64  `json:"durationMs"`
	Command    string `json:"command"`
	Skipped    bool   `json:"skipped"`
	SkipReason string `json:"skipReason,omitempty"`
}

func buildSafePath() string {
	basePaths := []string{"/usr/local/bin", "/usr/bin", "/bin"}
	extraPaths := []string{}

	for _, dir := range []string{
		"/opt/homebrew/bin",
		"/opt/homebrew/sbin",
		filepath.Join(os.Getenv("GOROOT"), "bin"),
		filepath.Join(os.Getenv("GOPATH"), "bin"),
		filepath.Join(os.Getenv("CARGO_HOME"), "bin"),
		filepath.Join(os.Getenv("JAVA_HOME"), "bin"),
		filepath.Join(os.Getenv("HOME"), ".local/bin"),
		filepath.Join(os.Getenv("HOME"), "go", "bin"),
	} {
		if dir != "" && dir != "/" {
			if info, err := os.Stat(dir); err == nil && info.IsDir() {
				extraPaths = append(extraPaths, dir)
			}
		}
	}

	currentPATH := os.Getenv("PATH")
	if currentPATH != "" {
		for _, p := range strings.Split(currentPATH, ":") {
			p = strings.TrimSpace(p)
			if p == "" {
				continue
			}
			found := false
			for _, existing := range basePaths {
				if existing == p {
					found = true
					break
				}
			}
			for _, existing := range extraPaths {
				if existing == p {
					found = true
					break
				}
			}
			if !found {
				if info, err := os.Stat(p); err == nil && info.IsDir() {
					extraPaths = append(extraPaths, p)
				}
			}
		}
	}

	allPaths := append(extraPaths, basePaths...)
	return strings.Join(allPaths, ":")
}

var buildCommands = []struct {
	detectFile string
	command    string
	args       []string
}{
	{"go.mod", "go", []string{"build", "./..."}},
	{"Cargo.toml", "cargo", []string{"check"}},
	{"package.json", "npm", []string{"run", "build"}},
	{"pom.xml", "mvn", []string{"compile", "-q"}},
	{"build.gradle", "gradle", []string{"compileJava", "-q"}},
	{"Makefile", "make", []string{}},
}

type buildTarget struct {
	cmd  string
	args []string
	dir  string
}

func (r *Repository) RunBuild(changedFiles []string) (*BuildResult, error) {
	return r.runBuildWithPath(changedFiles, buildSafePath())
}

func (r *Repository) runBuildWithPath(changedFiles []string, buildPath string) (*BuildResult, error) {
	if r.workDir == "" {
		return nil, fmt.Errorf("work directory not set")
	}

	targets := r.resolveBuildTargets(changedFiles)
	if len(targets) == 0 {
		return &BuildResult{Skipped: true, Success: true, SkipReason: "no_build_target"}, nil
	}

	var allOutput strings.Builder
	var totalDuration int64
	anyFailed := false
	ranAny := false
	missingTool := false
	var commands []string

	for _, t := range targets {
		commandPath, found := resolveBuildCommand(t.cmd, buildPath)
		if !found {
			missingTool = true
			anyFailed = true
			allOutput.WriteString(fmt.Sprintf("[%s] build tool %q not found, skipped\n", filepath.Base(t.dir), t.cmd))
			continue
		}

		start := time.Now()
		execCmd := exec.Command(commandPath, t.args...)
		execCmd.Dir = t.dir
		restrictedEnv := []string{
			"CI=true",
			"HOME=" + os.Getenv("HOME"),
			"PATH=" + buildPath,
			"LANG=en_US.UTF-8",
			"NODE_ENV=production",
			"GOPATH=" + os.Getenv("GOPATH"),
			"GOROOT=" + os.Getenv("GOROOT"),
			"CARGO_HOME=" + os.Getenv("CARGO_HOME"),
			"JAVA_HOME=" + os.Getenv("JAVA_HOME"),
			"http_proxy=",
			"https_proxy=",
			"HTTP_PROXY=",
			"HTTPS_PROXY=",
			"NO_PROXY=*",
		}
		execCmd.Env = restrictedEnv
		output, err := execCmd.CombinedOutput()
		duration := time.Since(start).Milliseconds()
		totalDuration += duration
		ranAny = true
		commands = append(commands, fmt.Sprintf("cd %s && %s %s", relativeBuildDir(r.workDir, t.dir), t.cmd, strings.Join(t.args, " ")))

		if err != nil {
			anyFailed = true
			allOutput.WriteString(fmt.Sprintf("[%s] FAILED (%dms)\n%s\nError: %v\n", relativeBuildDir(r.workDir, t.dir), duration, trimBuildOutput(string(output)), err))
		} else {
			allOutput.WriteString(fmt.Sprintf("[%s] OK (%dms)\n%s\n", relativeBuildDir(r.workDir, t.dir), duration, trimBuildOutput(string(output))))
		}
	}

	if !ranAny {
		skipReason := "missing_tool"
		if !missingTool {
			skipReason = "no_build_target"
		}
		return &BuildResult{Skipped: true, Success: !missingTool, Output: allOutput.String(), Command: "multi-target", SkipReason: skipReason}, nil
	}

	return &BuildResult{
		Success:    !anyFailed,
		Output:     allOutput.String(),
		Duration:   totalDuration,
		Command:    strings.Join(commands, " && "),
		SkipReason: buildSkipReason(missingTool),
	}, nil
}

func buildSkipReason(missingTool bool) string {
	if missingTool {
		return "missing_tool"
	}
	return ""
}

func (r *Repository) resolveBuildTargets(changedFiles []string) []buildTarget {
	if len(changedFiles) == 0 {
		if target, ok := findBuildTargetInDir(r.workDir); ok {
			return []buildTarget{target}
		}
		return nil
	}

	targetByDir := map[string]buildTarget{}
	for _, changedFile := range changedFiles {
		target, ok := r.findNearestBuildTarget(changedFile)
		if !ok {
			continue
		}
		targetByDir[target.dir] = target
	}

	targets := make([]buildTarget, 0, len(targetByDir))
	for _, target := range targetByDir {
		targets = append(targets, target)
	}
	sort.Slice(targets, func(i, j int) bool {
		return targets[i].dir < targets[j].dir
	})
	return targets
}

func (r *Repository) findNearestBuildTarget(changedFile string) (buildTarget, bool) {
	cleaned := filepath.Clean(filepath.FromSlash(changedFile))
	if cleaned == "." || strings.HasPrefix(cleaned, ".."+string(filepath.Separator)) || filepath.IsAbs(cleaned) {
		return buildTarget{}, false
	}

	dir := filepath.Join(r.workDir, filepath.Dir(cleaned))
	if info, err := os.Stat(filepath.Join(r.workDir, cleaned)); err == nil && info.IsDir() {
		dir = filepath.Join(r.workDir, cleaned)
	}

	absWorkDir, err := filepath.Abs(r.workDir)
	if err != nil {
		return buildTarget{}, false
	}
	for {
		absDir, err := filepath.Abs(dir)
		if err != nil || (absDir != absWorkDir && !strings.HasPrefix(absDir, absWorkDir+string(filepath.Separator))) {
			return buildTarget{}, false
		}
		if target, ok := findBuildTargetInDir(absDir); ok {
			return target, true
		}
		if absDir == absWorkDir {
			return buildTarget{}, false
		}
		dir = filepath.Dir(absDir)
	}
}

func findBuildTargetInDir(dir string) (buildTarget, bool) {
	for _, bc := range buildCommands {
		if _, err := os.Stat(filepath.Join(dir, bc.detectFile)); err == nil {
			return buildTarget{cmd: bc.command, args: bc.args, dir: dir}, true
		}
	}
	return buildTarget{}, false
}

func resolveBuildCommand(command, buildPath string) (string, bool) {
	for _, dir := range strings.Split(buildPath, ":") {
		path := filepath.Join(dir, command)
		if info, err := os.Stat(path); err == nil && !info.IsDir() {
			return path, true
		}
	}
	return "", false
}

func relativeBuildDir(workDir, dir string) string {
	rel, err := filepath.Rel(workDir, dir)
	if err != nil || rel == "." {
		return "."
	}
	return filepath.ToSlash(rel)
}

func trimBuildOutput(output string) string {
	const maxBuildOutput = 12000
	output = strings.TrimSpace(output)
	if len(output) <= maxBuildOutput {
		return output
	}
	return output[:maxBuildOutput] + "\n... output truncated ..."
}
