package handler

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

	"bug-agent/internal/model"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
)

type smtpTestMessage struct {
	from string
	to   string
	data string
}

func setupPlatformSettingsRouter(t testing.TB) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db

	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", uint(1))
		c.Next()
	})
	return r
}

func TestPlatformSettingsHandler_GetAndUpdateEmailSettings(t *testing.T) {
	r := setupPlatformSettingsRouter(t)

	h := NewPlatformSettingsHandler(model.DB)
	r.GET("/admin/platform-settings/email", h.GetEmailSettings)
	r.PUT("/admin/platform-settings/email", h.UpdateEmailSettings)

	getResp := httptest.NewRecorder()
	getReq, _ := http.NewRequest(http.MethodGet, "/admin/platform-settings/email", nil)
	r.ServeHTTP(getResp, getReq)
	if getResp.Code != http.StatusOK {
		t.Fatalf("default get expected 200, got %d: %s", getResp.Code, getResp.Body.String())
	}

	var emptyPayload map[string]interface{}
	_ = json.Unmarshal(getResp.Body.Bytes(), &emptyPayload)
	data := emptyPayload["data"].(map[string]interface{})
	if data["smtpHost"] != "" {
		t.Fatalf("expected empty smtpHost, got %v", data["smtpHost"])
	}
	if data["passwordConfigured"].(bool) {
		t.Fatalf("expected passwordConfigured false by default")
	}

	body := `{"smtpHost":"smtp.example.com","smtpPort":465,"smtpUser":"robot@example.com","smtpPassword":"smtp-secret","smtpFrom":"BugAgent <noreply@example.com>"}`
	updateResp := httptest.NewRecorder()
	updateReq, _ := http.NewRequest(http.MethodPut, "/admin/platform-settings/email", bytes.NewBufferString(body))
	updateReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(updateResp, updateReq)
	if updateResp.Code != http.StatusOK {
		t.Fatalf("update expected 200, got %d: %s", updateResp.Code, updateResp.Body.String())
	}

	verifyResp := httptest.NewRecorder()
	verifyReq, _ := http.NewRequest(http.MethodGet, "/admin/platform-settings/email", nil)
	r.ServeHTTP(verifyResp, verifyReq)
	if verifyResp.Code != http.StatusOK {
		t.Fatalf("verify get expected 200, got %d: %s", verifyResp.Code, verifyResp.Body.String())
	}

	var verifyPayload map[string]interface{}
	_ = json.Unmarshal(verifyResp.Body.Bytes(), &verifyPayload)
	verifyData := verifyPayload["data"].(map[string]interface{})
	if verifyData["smtpHost"] != "smtp.example.com" {
		t.Fatalf("expected smtpHost persisted")
	}
	if !verifyData["passwordConfigured"].(bool) {
		t.Fatalf("expected passwordConfigured true after update")
	}
}

func TestPlatformSettingsHandler_TestEmailSettings(t *testing.T) {
	r := setupPlatformSettingsRouter(t)
	h := NewPlatformSettingsHandler(model.DB)
	r.POST("/admin/platform-settings/email/test", h.TestEmailSettings)

	addr, msgCh, closeFn := startSMTPTestServer(t)
	defer closeFn()
	host, portRaw, _ := net.SplitHostPort(addr)
	port, _ := strconv.Atoi(portRaw)

	body := fmt.Sprintf(`{"smtpHost":"%s","smtpPort":%d,"smtpFrom":"noreply@example.com","to":"receiver@example.com"}`, host, port)
	resp := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost, "/admin/platform-settings/email/test", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(resp, req)

	if resp.Code != http.StatusOK {
		t.Fatalf("test email expected 200, got %d: %s", resp.Code, resp.Body.String())
	}

	select {
	case msg := <-msgCh:
		if !strings.Contains(msg.to, "receiver@example.com") {
			t.Fatalf("expected receiver@example.com, got %s", msg.to)
		}
		if !strings.Contains(msg.data, "BugAgent 平台邮件配置测试") {
			t.Fatalf("expected test email subject in smtp data")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("expected smtp test message to be sent")
	}
}

func startSMTPTestServer(t testing.TB) (string, <-chan smtpTestMessage, func()) {
	t.Helper()

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen smtp test server failed: %v", err)
	}
	msgCh := make(chan smtpTestMessage, 1)
	done := make(chan struct{})

	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				select {
				case <-done:
					return
				default:
					return
				}
			}
			go handleSMTPTestConn(conn, msgCh)
		}
	}()

	return ln.Addr().String(), msgCh, func() {
		close(done)
		_ = ln.Close()
	}
}

func handleSMTPTestConn(conn net.Conn, msgCh chan<- smtpTestMessage) {
	defer conn.Close()

	reader := bufio.NewReader(conn)
	writer := bufio.NewWriter(conn)
	writeSMTPLine(writer, "220 localhost Simple SMTP")

	var from string
	var to string

	for {
		line, err := reader.ReadString('\n')
		if err != nil {
			return
		}
		trimmed := strings.TrimSpace(line)
		upper := strings.ToUpper(trimmed)

		switch {
		case strings.HasPrefix(upper, "EHLO"), strings.HasPrefix(upper, "HELO"):
			writeSMTPLine(writer, "250-localhost")
			writeSMTPLine(writer, "250 OK")
		case strings.HasPrefix(upper, "MAIL FROM:"):
			from = trimmed
			writeSMTPLine(writer, "250 OK")
		case strings.HasPrefix(upper, "RCPT TO:"):
			to = trimmed
			writeSMTPLine(writer, "250 OK")
		case strings.HasPrefix(upper, "DATA"):
			writeSMTPLine(writer, "354 End data with <CR><LF>.<CR><LF>")
			var data strings.Builder
			for {
				chunk, err := reader.ReadString('\n')
				if err != nil {
					return
				}
				if strings.TrimSpace(chunk) == "." {
					break
				}
				data.WriteString(chunk)
			}
			msgCh <- smtpTestMessage{from: from, to: to, data: data.String()}
			writeSMTPLine(writer, "250 OK")
		case strings.HasPrefix(upper, "QUIT"):
			writeSMTPLine(writer, "221 Bye")
			return
		default:
			writeSMTPLine(writer, "250 OK")
		}
	}
}

func writeSMTPLine(writer *bufio.Writer, line string) {
	_, _ = writer.WriteString(line + "\r\n")
	_ = writer.Flush()
}
