package atmotube

import (
	"sync"
	"testing"
	"time"
)

func TestWithAdapterLockSerializesConcurrentOperations(t *testing.T) {
	client := &Client{}

	started := make(chan string, 2)
	release := make(chan struct{})
	results := make(chan string, 2)
	var wg sync.WaitGroup

	runLocked := func(label string) {
		defer wg.Done()
		client.withAdapterLock(func() {
			started <- label
			<-release
			results <- label
		})
	}

	wg.Add(2)
	go runLocked("first")
	firstStarted := <-started
	if firstStarted != "first" {
		t.Fatalf("expected first locked operation to start first, got %q", firstStarted)
	}

	go runLocked("second")

	select {
	case unexpected := <-started:
		t.Fatalf("expected second operation to wait for lock, but %q started early", unexpected)
	case <-time.After(100 * time.Millisecond):
	}

	release <- struct{}{}

	select {
	case secondStarted := <-started:
		if secondStarted != "second" {
			t.Fatalf("expected second operation after releasing lock, got %q", secondStarted)
		}
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for second locked operation to start")
	}

	release <- struct{}{}
	wg.Wait()
	close(results)

	completed := make([]string, 0, 2)
	for label := range results {
		completed = append(completed, label)
	}
	if len(completed) != 2 {
		t.Fatalf("expected both operations to complete, got %d", len(completed))
	}
}
