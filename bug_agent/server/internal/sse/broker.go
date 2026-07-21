package sse

import (
	"encoding/json"
	"sync"

	"bug-agent/pkg/logger"
)

type SSEEvent struct {
	Event string      `json:"event"`
	Data  interface{} `json:"data"`
}

type Broker struct {
	subscribers map[string]map[chan SSEEvent]bool
	mu          sync.RWMutex
}

var GlobalBroker *Broker

func InitBroker() {
	if GlobalBroker != nil {
		return
	}
	GlobalBroker = NewBroker()
}

func NewBroker() *Broker {
	return &Broker{
		subscribers: make(map[string]map[chan SSEEvent]bool),
	}
}

func (b *Broker) Subscribe(rooms []string) chan SSEEvent {
	ch := make(chan SSEEvent, 1024)

	b.mu.Lock()
	for _, room := range rooms {
		if _, exists := b.subscribers[room]; !exists {
			b.subscribers[room] = make(map[chan SSEEvent]bool)
		}
		b.subscribers[room][ch] = true
	}
	b.mu.Unlock()

	return ch
}

func (b *Broker) Unsubscribe(ch chan SSEEvent) {
	b.mu.Lock()
	found := false
	for room, clients := range b.subscribers {
		if _, exists := clients[ch]; exists {
			delete(clients, ch)
			if len(clients) == 0 {
				delete(b.subscribers, room)
			}
			found = true
		}
	}
	b.mu.Unlock()

	if found {
		close(ch)
	}
}

func (b *Broker) Publish(room string, event SSEEvent) {
	data, err := json.Marshal(event.Data)
	if err != nil {
		logger.Errorf("[SSE Broker] marshal event data failed: %v", err)
		return
	}

	msg := sseMessage{Event: event.Event, Data: data}

	b.mu.RLock()
	var failed []chan SSEEvent
	if clients, exists := b.subscribers[room]; exists {
		for ch := range clients {
			select {
			case ch <- SSEEvent{Event: msg.Event, Data: string(msg.Data)}:
			default:
				failed = append(failed, ch)
			}
		}
	}
	b.mu.RUnlock()

	if len(failed) > 0 {
		var toClose []chan SSEEvent
		b.mu.Lock()
		for _, ch := range failed {
			for room, clients := range b.subscribers {
				if _, exists := clients[ch]; exists {
					delete(clients, ch)
					if len(clients) == 0 {
						delete(b.subscribers, room)
					}
					toClose = append(toClose, ch)
				}
			}
		}
		b.mu.Unlock()

		for _, ch := range toClose {
			close(ch)
		}
	}
}

func (b *Broker) PublishGlobal(event SSEEvent) {
	b.mu.RLock()
	allRooms := make([]string, 0, len(b.subscribers))
	for room := range b.subscribers {
		allRooms = append(allRooms, room)
	}
	b.mu.RUnlock()

	for _, room := range allRooms {
		b.Publish(room, event)
	}
}

func (b *Broker) GetSubscriberCount() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	seen := make(map[chan SSEEvent]bool)
	count := 0
	for _, clients := range b.subscribers {
		for ch := range clients {
			if !seen[ch] {
				seen[ch] = true
				count++
			}
		}
	}
	return count
}

type sseMessage struct {
	Event string `json:"event"`
	Data  json.RawMessage `json:"data"`
}
