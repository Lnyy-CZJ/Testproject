package aiconfig

import (
	"bug-agent/internal/config"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"net/url"
	"strings"
)

func getEncryptionKey() ([]byte, error) {
	raw := config.C.Secrets.AIConfigEncryptionKey
	if raw == "" {
		return nil, errors.New("secrets.ai_config_encryption_key is required in config")
	}

	if decoded, err := base64.StdEncoding.DecodeString(raw); err == nil {
		if len(decoded) == 32 {
			return decoded, nil
		}
	}

	if len(raw) == 32 {
		return []byte(raw), nil
	}

	return nil, errors.New("secrets.ai_config_encryption_key must be 32-byte raw string or base64-encoded 32-byte value")
}

func EncryptAPIKey(plaintext string) (string, error) {
	if plaintext == "" {
		return "", nil
	}

	key, err := getEncryptionKey()
	if err != nil {
		return "", err
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return "", err
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}

	nonce := make([]byte, gcm.NonceSize())
	if _, err = io.ReadFull(rand.Reader, nonce); err != nil {
		return "", err
	}

	ciphertext := gcm.Seal(nonce, nonce, []byte(plaintext), nil)
	return base64.StdEncoding.EncodeToString(ciphertext), nil
}

func DecryptAPIKey(ciphertext string) (string, error) {
	if ciphertext == "" {
		return "", nil
	}

	key, err := getEncryptionKey()
	if err != nil {
		return "", err
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return "", err
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}

	data, err := base64.StdEncoding.DecodeString(ciphertext)
	if err != nil {
		return "", fmt.Errorf("base64 decode failed: %w", err)
	}

	nonceSize := gcm.NonceSize()
	if len(data) < nonceSize {
		return "", errors.New("ciphertext too short")
	}

	nonce, ciphertextBytes := data[:nonceSize], data[nonceSize:]
	plaintext, err := gcm.Open(nil, nonce, ciphertextBytes, nil)
	if err != nil {
		return "", fmt.Errorf("decrypt failed: %w", err)
	}

	return string(plaintext), nil
}

func MaskAPIKey(key string) string {
	if len(key) <= 8 {
		return key
	}
	return key[:4] + "****" + key[len(key)-4:]
}

func IsPlaceholderEndpoint(endpoint string) bool {
	trimmed := strings.TrimSpace(endpoint)
	if trimmed == "" {
		return false
	}

	u, err := url.Parse(trimmed)
	if err != nil {
		return false
	}

	host := strings.ToLower(u.Hostname())
	if host == "" {
		return false
	}

	return host == "example.invalid" || strings.HasSuffix(host, ".invalid")
}
