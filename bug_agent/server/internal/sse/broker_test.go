package sse

import (
	"fmt"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func BenchmarkSSEBroker_Publish(b *testing.B) {
	broker := NewBroker()
	ch := broker.Subscribe([]string{"defect:1"})

	go func() {
		for range ch {
		}
	}()

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		broker.Publish("defect:1", SSEEvent{
			Event: "defect:status_changed",
			Data:  map[string]interface{}{"defectId": 1},
		})
	}
	broker.Unsubscribe(ch)
}

func BenchmarkSSEBroker_ParallelPublish(b *testing.B) {
	broker := NewBroker()
	numSubscribers := 100

	var channels []chan SSEEvent
	for i := 0; i < numSubscribers; i++ {
		ch := broker.Subscribe([]string{fmt.Sprintf("defect:%d", i%10)})
		go func(c chan SSEEvent) {
			for range c {
			}
		}(ch)
		channels = append(channels, ch)
	}

	b.ResetTimer()
	b.RunParallel(func(pb *testing.PB) {
		i := 0
		for pb.Next() {
			broker.Publish(fmt.Sprintf("defect:%d", i%10), SSEEvent{
				Event: "test",
				Data:  i,
			})
			i++
		}
	})

	for _, ch := range channels {
		broker.Unsubscribe(ch)
	}
}

func BenchmarkSSEBroker_SubscribeUnsubscribe(b *testing.B) {
	broker := NewBroker()

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		ch := broker.Subscribe([]string{"defect:1"})
		broker.Unsubscribe(ch)
	}
}

func TestSSEBroker_Throughput(t *testing.T) {
	broker := NewBroker()
	numSubscribers := 50
	numEvents := 10000

	var received atomic.Int64
	var channels []chan SSEEvent

	for i := 0; i < numSubscribers; i++ {
		ch := broker.Subscribe([]string{"defect:1"})
		go func(c chan SSEEvent) {
			for range c {
				received.Add(1)
			}
		}(ch)
		channels = append(channels, ch)
	}

	start := time.Now()
	for i := 0; i < numEvents; i++ {
		broker.Publish("defect:1", SSEEvent{Event: "test", Data: i})
	}

	deadline := time.After(5 * time.Second)
	for received.Load() < int64(numEvents*numSubscribers) {
		select {
		case <-deadline:
			t.Fatalf("timeout: received %d/%d events", received.Load(), numEvents*numSubscribers)
		default:
			time.Sleep(10 * time.Millisecond)
		}
	}

	elapsed := time.Since(start)
	throughput := float64(received.Load()) / elapsed.Seconds()
	t.Logf("Throughput: %.0f events/sec (%d events to %d subscribers in %v)",
		throughput, received.Load(), numSubscribers, elapsed)

	for _, ch := range channels {
		broker.Unsubscribe(ch)
	}
}

func TestSSEBroker_ConcurrentPublish(t *testing.T) {
	broker := NewBroker()
	numConsumers := 10
	ch := broker.Subscribe([]string{"defect:1"})

	var received atomic.Int64
	for i := 0; i < numConsumers; i++ {
		go func() {
			for range ch {
				received.Add(1)
			}
		}()
	}

	numPublishers := 10
	eventsPerPublisher := 1000
	var wg sync.WaitGroup

	start := time.Now()
	for p := 0; p < numPublishers; p++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := 0; i < eventsPerPublisher; i++ {
				broker.Publish("defect:1", SSEEvent{Event: "test", Data: i})
			}
		}()
	}

	wg.Wait()
	time.Sleep(500 * time.Millisecond)

	elapsed := time.Since(start)
	totalPublished := numPublishers * eventsPerPublisher
	t.Logf("Concurrent publish: %d publishers × %d events = %d published, %d received in %v (%.0f events/sec)",
		numPublishers, eventsPerPublisher, totalPublished, received.Load(), elapsed, float64(received.Load())/elapsed.Seconds())

	if received.Load() == 0 {
		t.Fatal("no events received")
	}

	broker.Unsubscribe(ch)
}
