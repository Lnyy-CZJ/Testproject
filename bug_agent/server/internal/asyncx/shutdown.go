package asyncx

import "context"

var (
	shutdownCtx    context.Context
	shutdownCancel context.CancelFunc
)

func init() {
	shutdownCtx, shutdownCancel = context.WithCancel(context.Background())
}

func ShutdownContext() context.Context {
	return shutdownCtx
}

func TriggerShutdown() {
	shutdownCancel()
}
