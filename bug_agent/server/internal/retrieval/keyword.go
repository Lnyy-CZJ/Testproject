package retrieval

import (
	"bug-agent/pkg/logger"
	"context"
	"sort"
	"strings"
)

type KeywordRetriever struct{}

func NewKeywordRetriever() *KeywordRetriever {
	return &KeywordRetriever{}
}

func (r *KeywordRetriever) Name() string {
	return "keyword"
}

func (r *KeywordRetriever) Retrieve(_ context.Context, query Query) ([]Evidence, error) {
	if query.Repo == nil {
		return nil, nil
	}
	topK := query.TopK
	if topK <= 0 {
		topK = 10
	}

	keywords := normalizeKeywords(query.Keywords)
	if len(keywords) == 0 {
		keywords = ExtractKeywords(query.Text)
	}
	if len(keywords) == 0 {
		return nil, nil
	}

	allFiles, err := query.Repo.ListFiles("")
	if err != nil {
		return nil, err
	}

	type scoreItem struct {
		file  string
		score float64
	}
	scores := make(map[string]float64)
	for _, file := range allFiles {
		lowerFile := strings.ToLower(file)
		for _, keyword := range keywords {
			if strings.Contains(lowerFile, keyword) {
				scores[file] += 10
			}
		}
	}

	for _, keyword := range keywords {
		matches, err := query.Repo.SearchFiles(keyword, topK*3)
		if err != nil {
			logger.Warnf("SearchFiles failed: keyword=%s err=%v", keyword, err)
		}
		for _, match := range matches {
			scores[match] += 3
		}
	}

	ranked := make([]scoreItem, 0, len(scores))
	for file, score := range scores {
		if score <= 0 {
			continue
		}
		ranked = append(ranked, scoreItem{file: file, score: score})
	}

	sort.Slice(ranked, func(i, j int) bool {
		if ranked[i].score == ranked[j].score {
			return ranked[i].file < ranked[j].file
		}
		return ranked[i].score > ranked[j].score
	})
	if len(ranked) > topK {
		ranked = ranked[:topK]
	}

	result := make([]Evidence, 0, len(ranked))
	for _, item := range ranked {
		result = append(result, Evidence{
			FilePath: item.file,
			Score:    item.score,
			Source:   r.Name(),
		})
	}
	return result, nil
}

func normalizeKeywords(keywords []string) []string {
	result := make([]string, 0, len(keywords))
	seen := make(map[string]struct{})
	for _, keyword := range keywords {
		normalized := strings.TrimSpace(strings.ToLower(keyword))
		if normalized == "" {
			continue
		}
		if _, ok := seen[normalized]; ok {
			continue
		}
		seen[normalized] = struct{}{}
		result = append(result, normalized)
	}
	return result
}

// ExtractKeywords extracts retrieval keywords from defect text.
func ExtractKeywords(text string) []string {
	words := strings.Fields(strings.ToLower(text))
	stopWords := map[string]bool{
		"the": true, "is": true, "at": true, "which": true, "on": true,
		"and": true, "or": true, "but": true, "in": true, "with": true,
		"to": true, "for": true, "of": true, "a": true, "an": true,
		"bug": true, "issue": true, "error": true, "problem": true,
		"缺陷": true, "问题": true, "错误": true, "异常": true,
		"的": true, "了": true, "在": true, "是": true, "有": true,
	}

	keywordSet := make(map[string]bool)
	for _, word := range words {
		word = strings.Trim(word, ".,!?;:'\"()[]{}")
		if len(word) > 2 && !stopWords[word] {
			keywordSet[word] = true
		}
	}

	keywords := make([]string, 0, len(keywordSet))
	for word := range keywordSet {
		keywords = append(keywords, word)
	}
	sort.Strings(keywords)

	if len(keywords) > 20 {
		keywords = keywords[:20]
	}

	return keywords
}
