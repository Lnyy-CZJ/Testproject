package git

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/go-git/go-git/v5"
	"github.com/go-git/go-git/v5/config"
	"github.com/go-git/go-git/v5/plumbing"
	"github.com/go-git/go-git/v5/plumbing/object"
	githttp "github.com/go-git/go-git/v5/plumbing/transport/http"
	"github.com/go-git/go-git/v5/storage/memory"
)

// Repository Git仓库封装
type Repository struct {
	repo        *git.Repository
	workDir     string
	url         string
	branch      string
	clonedAt    time.Time
	skipCleanup bool
}

// CloneOptions 克隆选项
type CloneOptions struct {
	URL          string
	Branch       string // 目标分支，默认为main/master
	Auth         Auth   // 认证信息（可选）
	Depth        int    // 浅克隆深度，0表示完整克隆
	SingleBranch bool   // 是否只克隆指定分支
}

// Auth 认证信息
type Auth struct {
	Username string // 用户名或token
	Password string // 密码（使用token时可以为空）
	Token    string // Personal Access Token
}

// NewRepository 克隆远程仓库
func NewRepository(ctx context.Context, opts CloneOptions) (*Repository, error) {
	if opts.URL == "" {
		return nil, fmt.Errorf("repository URL is required")
	}

	tmpDir, err := os.MkdirTemp("", "bug-agent-repo-*")
	if err != nil {
		return nil, fmt.Errorf("create temp dir failed: %w", err)
	}

	var cloneOpts *git.CloneOptions

	if authMethod := buildHTTPAuthMethod(opts.Auth); authMethod != nil {
		cloneOpts = &git.CloneOptions{
			URL:          opts.URL,
			SingleBranch: opts.SingleBranch,
			Depth:        opts.Depth,
			Auth:         authMethod,
		}
	} else {
		cloneOpts = &git.CloneOptions{
			URL:          opts.URL,
			SingleBranch: opts.SingleBranch,
			Depth:        opts.Depth,
		}
	}

	repo, err := git.PlainCloneContext(ctx, tmpDir, false, cloneOpts)
	if err != nil {
		os.RemoveAll(tmpDir)
		return nil, fmt.Errorf("clone repository failed: %w", err)
	}

	branch := opts.Branch
	if branch == "" {
		head, err := repo.Head()
		if err == nil {
			branch = head.Name().Short()
		} else {
			branch = "main" // 默认分支
		}
	} else {
		// 切换到指定分支
		worktree, err := repo.Worktree()
		if err != nil {
			os.RemoveAll(tmpDir)
			return nil, fmt.Errorf("get worktree failed: %w", err)
		}

		err = worktree.Checkout(&git.CheckoutOptions{
			Branch: plumbing.NewBranchReferenceName(branch),
		})
		if err != nil {
			// 尝试创建并切换到新分支
			err = worktree.Checkout(&git.CheckoutOptions{
				Create: true,
				Branch: plumbing.NewBranchReferenceName(branch),
			})
			if err != nil {
				os.RemoveAll(tmpDir)
				return nil, fmt.Errorf("checkout branch %s failed: %w", branch, err)
			}
		}
	}

	return &Repository{
		repo:     repo,
		workDir:  tmpDir,
		url:      opts.URL,
		branch:   branch,
		clonedAt: time.Now(),
	}, nil
}

func CloneToDir(ctx context.Context, dir string, opts CloneOptions) (*Repository, error) {
	if opts.URL == "" {
		return nil, fmt.Errorf("repository URL is required")
	}

	var cloneOpts *git.CloneOptions

	if authMethod := buildHTTPAuthMethod(opts.Auth); authMethod != nil {
		cloneOpts = &git.CloneOptions{
			URL:          opts.URL,
			SingleBranch: opts.SingleBranch,
			Depth:        opts.Depth,
			Auth:         authMethod,
		}
	} else {
		cloneOpts = &git.CloneOptions{
			URL:          opts.URL,
			SingleBranch: opts.SingleBranch,
			Depth:        opts.Depth,
		}
	}

	repo, err := git.PlainCloneContext(ctx, dir, false, cloneOpts)
	if err != nil {
		return nil, fmt.Errorf("clone repository failed: %w", err)
	}

	branch := opts.Branch
	if branch == "" {
		head, err := repo.Head()
		if err == nil {
			branch = head.Name().Short()
		} else {
			branch = "main"
		}
	} else {
		worktree, err := repo.Worktree()
		if err != nil {
			return nil, fmt.Errorf("get worktree failed: %w", err)
		}

		err = worktree.Checkout(&git.CheckoutOptions{
			Branch: plumbing.NewBranchReferenceName(branch),
		})
		if err != nil {
			err = worktree.Checkout(&git.CheckoutOptions{
				Create: true,
				Branch: plumbing.NewBranchReferenceName(branch),
			})
			if err != nil {
				return nil, fmt.Errorf("checkout branch %s failed: %w", branch, err)
			}
		}
	}

	return &Repository{
		repo:     repo,
		workDir:  dir,
		url:      opts.URL,
		branch:   branch,
		clonedAt: time.Now(),
	}, nil
}

func OpenLocalRepository(dir, url, branch string) (*Repository, error) {
	if dir == "" {
		return nil, fmt.Errorf("repository directory is required")
	}
	info, err := os.Stat(dir)
	if err != nil {
		return nil, fmt.Errorf("stat local repository failed: %w", err)
	}
	if !info.IsDir() {
		return nil, fmt.Errorf("local repository path is not a directory: %s", dir)
	}

	return &Repository{
		workDir:     dir,
		url:         url,
		branch:      branch,
		clonedAt:    time.Now(),
		skipCleanup: true,
	}, nil
}

// ReadFile 读取文件内容
func (r *Repository) ReadFile(path string) (string, error) {
	fullPath := filepath.Join(r.workDir, path)

	content, err := os.ReadFile(fullPath)
	if err != nil {
		return "", fmt.Errorf("read file %s failed: %w", path, err)
	}

	return string(content), nil
}

func (r *Repository) ListDir(path string) ([]DirEntry, error) {
	fullPath := filepath.Join(r.workDir, path)
	entries, err := os.ReadDir(fullPath)
	if err != nil {
		return nil, fmt.Errorf("list dir %s failed: %w", path, err)
	}
	var result []DirEntry
	for _, e := range entries {
		if strings.HasPrefix(e.Name(), ".") {
			continue
		}
		entryType := "file"
		if e.IsDir() {
			entryType = "dir"
		}
		result = append(result, DirEntry{Name: e.Name(), Type: entryType, IsDir: e.IsDir()})
	}
	return result, nil
}

type DirEntry struct {
	Name  string
	Type  string
	IsDir bool
}

// SearchFiles 根据关键词搜索相关文件
func (r *Repository) SearchFiles(keyword string, maxResults int) ([]string, error) {
	if maxResults <= 0 {
		maxResults = 20
	}

	var results []string

	err := filepath.Walk(r.workDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return nil
		}

		if info.IsDir() {
			// 跳过.git目录和隐藏目录
			if strings.HasPrefix(info.Name(), ".") {
				return filepath.SkipDir
			}
			return nil
		}

		// 跳过大文件和非文本文件
		if info.Size() > 1024*1024 { // 大于1MB的文件跳过
			return nil
		}

		ext := strings.ToLower(filepath.Ext(path))
		supportedExts := map[string]bool{
			".go":   true,
			".js":   true,
			".ts":   true,
			".tsx":  true,
			".jsx":  true,
			".py":   true,
			".java": true,
			".rb":   true,
			".php":  true,
			".cs":   true,
			".cpp":  true,
			".c":    true,
			".h":    true,
			".html": true,
			".css":  true,
			".scss": true,
			".less": true,
			".vue":  true,
			".sql":  true,
			".xml":  true,
			".yaml": true,
			".yml":  true,
			".json": true,
			".md":   true,
			".txt":  true,
			".sh":   true,
			".bat":  true,
		}

		if !supportedExts[ext] {
			return nil
		}

		content, err := os.ReadFile(path)
		if err != nil {
			return nil
		}

		if strings.Contains(string(content), keyword) {
			relPath, _ := filepath.Rel(r.workDir, path)
			results = append(results, relPath)

			if len(results) >= maxResults {
				return fmt.Errorf("max results reached")
			}
		}

		return nil
	})

	if err != nil && err.Error() != "max results reached" {
		return results, err
	}

	return results, nil
}

// GetFileHistory 获取文件的最近修改记录
func (r *Repository) GetFileHistory(path string, limit int) ([]CommitInfo, error) {
	if r.repo == nil {
		return nil, fmt.Errorf("git metadata unavailable for local worktree")
	}
	if limit <= 0 {
		limit = 10
	}

	fullPath := filepath.Join(r.workDir, path)

	logIter, err := r.repo.Log(&git.LogOptions{
		FileName: &fullPath,
		Order:    git.LogOrderCommitterTime,
	})
	if err != nil {
		return nil, fmt.Errorf("get file history failed: %w", err)
	}

	defer logIter.Close()

	var commits []CommitInfo
	count := 0

	err = logIter.ForEach(func(c *object.Commit) error {
		commit := CommitInfo{
			Hash:    c.Hash.String()[:7],
			Message: c.Message,
			Author:  c.Author.Name,
			Date:    c.Author.When.Format("2006-01-02 15:04:05"),
		}

		commits = append(commits, commit)
		count++

		if count >= limit {
			return fmt.Errorf("limit reached")
		}

		return nil
	})

	if err != nil && err.Error() != "limit reached" {
		return commits, err
	}

	return commits, nil
}

// GetDirectoryStructure 获取目录结构
func (r *Repository) GetDirectoryStructure(maxDepth int) (*DirNode, error) {
	root := &DirNode{
		Name:     ".",
		Path:     ".",
		IsDir:    true,
		Children: make([]*DirNode, 0),
	}

	err := r.buildDirTree(root, ".", 0, maxDepth)
	if err != nil {
		return nil, err
	}

	return root, nil
}

// buildDirTree 递归构建目录树
func (r *Repository) buildDirTree(node *DirNode, dirPath string, currentDepth, maxDepth int) error {
	if maxDepth > 0 && currentDepth >= maxDepth {
		return nil
	}

	entries, err := os.ReadDir(filepath.Join(r.workDir, dirPath))
	if err != nil {
		return err
	}

	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), ".") {
			continue
		}

		childPath := filepath.Join(dirPath, entry.Name())
		relPath, _ := filepath.Rel(r.workDir, childPath)

		childNode := &DirNode{
			Name:  entry.Name(),
			Path:  relPath,
			IsDir: entry.IsDir(),
		}

		node.Children = append(node.Children, childNode)

		if entry.IsDir() {
			childNode.Children = make([]*DirNode, 0)
			r.buildDirTree(childNode, childPath, currentDepth+1, maxDepth)
		}
	}

	return nil
}

// Cleanup 清理临时目录
func (r *Repository) Cleanup() error {
	if r.skipCleanup {
		return nil
	}
	if r.workDir != "" {
		return os.RemoveAll(r.workDir)
	}
	return nil
}

// GetURL 获取仓库URL
func (r *Repository) GetURL() string {
	return r.url
}

// GetBranch 获取当前分支
func (r *Repository) GetBranch() string {
	return r.branch
}

// GetWorkDir 获取工作目录
func (r *Repository) GetWorkDir() string {
	return r.workDir
}

// DirNode 目录节点
type DirNode struct {
	Name     string     `json:"name"`
	Path     string     `json:"path"`
	IsDir    bool       `json:"isDir"`
	Size     int64      `json:"size,omitempty"`
	Children []*DirNode `json:"children,omitempty"`
}

// CommitInfo 提交信息
type CommitInfo struct {
	Hash    string `json:"hash"`
	Message string `json:"message"`
	Author  string `json:"author"`
	Date    string `json:"date"`
}

func buildHTTPAuthMethod(auth Auth) *githttp.BasicAuth {
	if strings.TrimSpace(auth.Token) != "" {
		username := strings.TrimSpace(auth.Username)
		if username == "" {
			username = "oauth2"
		}
		password := auth.Password
		if password == "" {
			password = auth.Token
		}
		return &githttp.BasicAuth{
			Username: username,
			Password: password,
		}
	}

	if strings.TrimSpace(auth.Username) != "" && auth.Password != "" {
		return &githttp.BasicAuth{
			Username: strings.TrimSpace(auth.Username),
			Password: auth.Password,
		}
	}

	return nil
}

func ListRemoteBranches(ctx context.Context, repoURL string, auth Auth) ([]string, error) {
	storage := memory.NewStorage()
	remote := git.NewRemote(storage, &config.RemoteConfig{
		Name: "origin",
		URLs: []string{repoURL},
	})

	var listOpts *git.ListOptions
	if authMethod := buildHTTPAuthMethod(auth); authMethod != nil {
		listOpts = &git.ListOptions{Auth: authMethod}
	}

	refs, err := remote.ListContext(ctx, listOpts)
	if err != nil {
		return nil, fmt.Errorf("list remote refs failed: %w", err)
	}
	return extractBranchNames(refs), nil
}

func extractBranchNames(refs []*plumbing.Reference) []string {
	seen := make(map[string]struct{})
	var branches []string
	for _, ref := range refs {
		name := ref.Name()
		if name.IsBranch() {
			short := name.Short()
			if _, ok := seen[short]; !ok {
				seen[short] = struct{}{}
				branches = append(branches, short)
			}
		}
	}
	return branches
}
