package asyncx

import (
	"bug-agent/pkg/logger"
	"os"
	"runtime/debug"
	"strings"
	"sync"
	"time"
)

var tracked sync.WaitGroup

func TestMode() bool {
	return envEnabled("BUG_AGENT_TEST_MODE")
}

func BackgroundWorkersDisabled() bool {
	return envEnabled("BUG_AGENT_DISABLE_BACKGROUND_WORKERS") || TestMode()
}

func Go(fn func()) {
	wrapped := func() {
		defer func() {
			if r := recover(); r != nil {
				logger.Infof("[asyncx.Go] panic recovered: %v\n%s", r, debug.Stack())
			}
		}()
		fn()
	}

	if TestMode() {
		tracked.Add(1)
		go func() {
			defer tracked.Done()
			wrapped()
		}()
		return
	}
	go wrapped()
}

func Wait(timeout time.Duration) bool {
	if !TestMode() {
		return true
	}

	done := make(chan struct{})
	go func() {
		tracked.Wait()
		close(done)
	}()

	select {
	case <-done:
		return true
	case <-time.After(timeout):
		return false
	}
}

func envEnabled(key string) bool {
	v := strings.TrimSpace(os.Getenv(key))
	return v == "1" || strings.EqualFold(v, "true")
}
