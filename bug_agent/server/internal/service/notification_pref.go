package service

import (
	"bug-agent/internal/model"
	"errors"
	"sort"
	"strings"

	"gorm.io/gorm"
)

type NotificationPrefService struct {
	db *gorm.DB
}

func NewNotificationPrefService(db *gorm.DB) *NotificationPrefService {
	return &NotificationPrefService{db: db}
}

var ErrInvalidNotificationCategory = errors.New("invalid notification category")
var ErrInvalidNotificationChannels = errors.New("invalid notification channels")

var defaultCategories = []struct {
	category string
	channels string
}{
	{"defect_assigned", "in_app,email"},
	{"defect_status_change", "in_app,email"},
	{"defect_mention", "in_app,email"},
	{"defect_due_soon", "in_app,email"},
	{"iteration_start", "in_app"},
	{"iteration_end", "in_app,email"},
	{"collaboration_complete", "in_app"},
	{"system_announce", "in_app,email"},
}

var supportedChannelOrder = []string{"in_app", "email", "webhook"}

var supportedCategorySet = func() map[string]struct{} {
	m := make(map[string]struct{}, len(defaultCategories))
	for _, item := range defaultCategories {
		m[item.category] = struct{}{}
	}
	return m
}()

func (s *NotificationPrefService) GetPreferences(userID uint) ([]model.NotificationPreference, error) {
	if err := s.ensureDefaultCategories(userID); err != nil {
		return nil, err
	}

	var prefs []model.NotificationPreference
	if err := s.db.Where("user_id = ?", userID).Find(&prefs).Error; err != nil {
		return nil, err
	}
	return s.sortByCategoryOrder(prefs), nil
}

func (s *NotificationPrefService) ensureDefaultCategories(userID uint) error {
	for _, dc := range defaultCategories {
		var pref model.NotificationPreference
		err := s.db.Where("user_id = ? AND category = ?", userID, dc.category).
			Attrs(model.NotificationPreference{
				UserID:   userID,
				Category: dc.category,
				Channels: dc.channels,
			}).
			FirstOrCreate(&pref).Error
		if err != nil {
			return err
		}
	}
	return nil
}

func (s *NotificationPrefService) UpdatePreference(userID, id uint, channels string) (*model.NotificationPreference, error) {
	var pref model.NotificationPreference
	if err := s.db.Where("id = ? AND user_id = ?", id, userID).First(&pref).Error; err != nil {
		return nil, err
	}

	category := normalizeCategory(pref.Category)
	if !isSupportedCategory(category) {
		return nil, ErrInvalidNotificationCategory
	}

	normalizedChannels, err := normalizeChannels(channels)
	if err != nil {
		return nil, err
	}

	pref.Category = category
	pref.Channels = normalizedChannels
	if err := s.db.Save(&pref).Error; err != nil {
		return nil, err
	}
	return &pref, nil
}

func (s *NotificationPrefService) BatchUpdate(userID uint, updates map[string]string) error {
	for category, channels := range updates {
		normalizedCategory := normalizeCategory(category)
		if !isSupportedCategory(normalizedCategory) {
			return ErrInvalidNotificationCategory
		}

		normalizedChannels, err := normalizeChannels(channels)
		if err != nil {
			return err
		}

		var pref model.NotificationPreference
		result := s.db.Where("user_id = ? AND category = ?", userID, normalizedCategory).
			Attrs(model.NotificationPreference{
				UserID:   userID,
				Category: normalizedCategory,
				Channels: normalizedChannels,
			}).
			FirstOrCreate(&pref)
		if result.Error != nil {
			return result.Error
		}
		pref.Channels = normalizedChannels
		if err := s.db.Save(&pref).Error; err != nil {
			return err
		}
	}
	return nil
}

func (s *NotificationPrefService) IsEnabled(userID uint, category, channel string) bool {
	category = normalizeCategory(category)
	channel = strings.TrimSpace(channel)

	if !isSupportedCategory(category) {
		return true
	}

	var pref model.NotificationPreference
	if err := s.db.Where("user_id = ? AND category = ?", userID, category).First(&pref).Error; err != nil {
		return true
	}
	channels := strings.Split(pref.Channels, ",")
	for _, c := range channels {
		if strings.TrimSpace(c) == channel {
			return true
		}
	}
	return false
}

func (s *NotificationPrefService) sortByCategoryOrder(prefs []model.NotificationPreference) []model.NotificationPreference {
	order := make(map[string]int, len(defaultCategories))
	for i, dc := range defaultCategories {
		order[dc.category] = i
	}

	sorted := make([]model.NotificationPreference, len(prefs))
	copy(sorted, prefs)
	sort.SliceStable(sorted, func(i, j int) bool {
		oi, iok := order[sorted[i].Category]
		oj, jok := order[sorted[j].Category]
		if iok && jok {
			return oi < oj
		}
		if iok {
			return true
		}
		if jok {
			return false
		}
		return sorted[i].Category < sorted[j].Category
	})
	return sorted
}

func normalizeCategory(category string) string {
	return strings.TrimSpace(category)
}

func normalizeChannels(raw string) (string, error) {
	if strings.TrimSpace(raw) == "" {
		return "", nil
	}

	allowed := make(map[string]struct{}, len(supportedChannelOrder))
	for _, ch := range supportedChannelOrder {
		allowed[ch] = struct{}{}
	}

	seen := make(map[string]struct{})
	for _, part := range strings.Split(raw, ",") {
		ch := strings.TrimSpace(part)
		if ch == "" {
			continue
		}
		if _, ok := allowed[ch]; !ok {
			return "", ErrInvalidNotificationChannels
		}
		seen[ch] = struct{}{}
	}

	ordered := make([]string, 0, len(seen))
	for _, standard := range supportedChannelOrder {
		if _, ok := seen[standard]; ok {
			ordered = append(ordered, standard)
		}
	}

	return strings.Join(ordered, ","), nil
}

func isSupportedCategory(category string) bool {
	_, ok := supportedCategorySet[category]
	return ok
}
