package shell

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"runtime"
	"time"
)

type Request struct {
	Command        string `json:"command"`
	Cwd            string `json:"cwd"`
	Shell          string `json:"shell"`
	TimeoutSeconds int    `json:"timeout_seconds"`
	MaxOutputChars int    `json:"max_output_chars"`
}

type Response struct {
	Runner       string `json:"runner"`
	Command      string `json:"command"`
	Cwd          string `json:"cwd"`
	ExitCode     int    `json:"exit_code"`
	Stdout       string `json:"stdout"`
	Stderr       string `json:"stderr"`
	DurationMS   int64  `json:"duration_ms"`
	TimedOut     bool   `json:"timed_out"`
	Truncated    bool   `json:"truncated"`
	ErrorMessage string `json:"error,omitempty"`
}

func Run(ctx context.Context, req Request) Response {
	started := time.Now()
	resp := Response{
		Runner:   "go",
		Command:  req.Command,
		Cwd:      req.Cwd,
		ExitCode: -1,
	}
	if req.Command == "" {
		resp.ErrorMessage = "command is required"
		resp.DurationMS = elapsedMS(started)
		return resp
	}
	if req.Cwd == "" {
		req.Cwd = "."
		resp.Cwd = "."
	}
	if req.Shell == "" {
		req.Shell = defaultShell()
	}
	if req.TimeoutSeconds <= 0 {
		req.TimeoutSeconds = 20
	}
	if req.MaxOutputChars <= 0 {
		req.MaxOutputChars = 12000
	}

	runCtx, cancel := context.WithTimeout(ctx, time.Duration(req.TimeoutSeconds)*time.Second)
	defer cancel()

	cmd := exec.CommandContext(runCtx, req.Shell, "-c", req.Command)
	cmd.Dir = req.Cwd
	setProcessGroup(cmd)

	stdout := &limitedBuffer{maxBytes: req.MaxOutputChars}
	stderr := &limitedBuffer{maxBytes: req.MaxOutputChars}
	cmd.Stdout = stdout
	cmd.Stderr = stderr

	err := cmd.Start()
	if err != nil {
		resp.ErrorMessage = err.Error()
		resp.DurationMS = elapsedMS(started)
		return resp
	}

	err = cmd.Wait()
	if errors.Is(runCtx.Err(), context.DeadlineExceeded) {
		resp.TimedOut = true
		killProcessGroup(cmd)
	}

	resp.DurationMS = elapsedMS(started)
	resp.Stdout = stdout.String()
	resp.Stderr = stderr.String()
	resp.Truncated = stdout.truncated || stderr.truncated
	if cmd.ProcessState != nil {
		resp.ExitCode = cmd.ProcessState.ExitCode()
	}
	if err != nil && resp.ErrorMessage == "" && resp.ExitCode == -1 {
		resp.ErrorMessage = err.Error()
	}
	return resp
}

func EncodeResponse(resp Response) ([]byte, error) {
	return json.Marshal(resp)
}

type limitedBuffer struct {
	maxBytes  int
	buf       bytes.Buffer
	truncated bool
}

func (b *limitedBuffer) Write(p []byte) (int, error) {
	if b.maxBytes <= 0 {
		b.truncated = true
		return len(p), nil
	}
	remaining := b.maxBytes - b.buf.Len()
	if remaining <= 0 {
		b.truncated = true
		return len(p), nil
	}
	if len(p) > remaining {
		b.truncated = true
		_, _ = b.buf.Write(p[:remaining])
		return len(p), nil
	}
	_, _ = b.buf.Write(p)
	return len(p), nil
}

func (b *limitedBuffer) String() string {
	return b.buf.String()
}

func elapsedMS(started time.Time) int64 {
	return time.Since(started).Milliseconds()
}

func defaultShell() string {
	if shell := os.Getenv("SHELL"); shell != "" {
		return shell
	}
	if runtime.GOOS == "windows" {
		return "cmd"
	}
	return "/bin/sh"
}
