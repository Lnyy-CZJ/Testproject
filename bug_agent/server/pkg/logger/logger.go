package logger

import (
	"fmt"
	"log/slog"
	"os"
)

func Init(debug bool) {
	level := slog.LevelInfo
	if debug {
		level = slog.LevelDebug
	}
	handler := slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{Level: level})
	slog.SetDefault(slog.New(handler))
}

func Info(msg string, args ...any)  { slog.Info(msg, args...) }
func Warn(msg string, args ...any)  { slog.Warn(msg, args...) }
func Error(msg string, args ...any) { slog.Error(msg, args...) }
func Debug(msg string, args ...any) { slog.Debug(msg, args...) }

func Infof(format string, args ...any)  { slog.Info(fmt.Sprintf(format, args...)) }
func Warnf(format string, args ...any)  { slog.Warn(fmt.Sprintf(format, args...)) }
func Errorf(format string, args ...any) { slog.Error(fmt.Sprintf(format, args...)) }
func Debugf(format string, args ...any) { slog.Debug(fmt.Sprintf(format, args...)) }
