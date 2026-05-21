package shell

import (
	"context"
	"testing"
	"time"
)

func TestRunCapturesOutputAndMarksGoRunner(t *testing.T) {
	resp := Run(context.Background(), Request{
		Command:        "printf 'hello'",
		Cwd:            ".",
		Shell:          "/bin/sh",
		TimeoutSeconds: 5,
		MaxOutputChars: 1000,
	})

	if resp.Runner != "go" {
		t.Fatalf("runner = %q, want go", resp.Runner)
	}
	if resp.ExitCode != 0 {
		t.Fatalf("exit code = %d, stderr = %q", resp.ExitCode, resp.Stderr)
	}
	if resp.Stdout != "hello" {
		t.Fatalf("stdout = %q, want hello", resp.Stdout)
	}
}

func TestRunTruncatesLargeOutput(t *testing.T) {
	resp := Run(context.Background(), Request{
		Command:        "printf 'abcdef'",
		Cwd:            ".",
		Shell:          "/bin/sh",
		TimeoutSeconds: 5,
		MaxOutputChars: 3,
	})

	if resp.Stdout != "abc" {
		t.Fatalf("stdout = %q, want abc", resp.Stdout)
	}
	if !resp.Truncated {
		t.Fatal("expected truncated output")
	}
}

func TestRunTimesOutLongRunningCommand(t *testing.T) {
	started := time.Now()
	resp := Run(context.Background(), Request{
		Command:        "sleep 5",
		Cwd:            ".",
		Shell:          "/bin/sh",
		TimeoutSeconds: 1,
		MaxOutputChars: 1000,
	})

	if !resp.TimedOut {
		t.Fatalf("timed out = false, response = %+v", resp)
	}
	if elapsed := time.Since(started); elapsed > 3*time.Second {
		t.Fatalf("timeout took %s, want under 3s", elapsed)
	}
}
