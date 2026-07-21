package adk

import (
	"container/heap"
	"context"
	"fmt"
	"sync"
	"time"

	"bug-agent/pkg/logger"

	"golang.org/x/sync/semaphore"
)

type TaskPriority int

const (
	PriorityUser       TaskPriority = 0
	PriorityAuto       TaskPriority = 1
	PriorityBackground TaskPriority = 2
)

type TaskStatus string

const (
	TaskStatusQueued    TaskStatus = "queued"
	TaskStatusRunning   TaskStatus = "running"
	TaskStatusCompleted TaskStatus = "completed"
	TaskStatusCancelled TaskStatus = "cancelled"
	TaskStatusFailed    TaskStatus = "failed"
)

type AnalysisTask struct {
	ID          string
	DefectID    uint
	AgentTypes  []string
	Priority    TaskPriority
	Ctx         context.Context
	Cancel      context.CancelFunc
	ResultCh    chan<- *AnalysisResult
	SubmittedAt time.Time
}

type AnalysisResult struct {
	TaskID  string
	DefectID uint
	Status  TaskStatus
	Error   error
}

type TaskStatusInfo struct {
	TaskID      string
	DefectID    uint
	Priority    TaskPriority
	Status      TaskStatus
	SubmittedAt time.Time
	StartedAt   *time.Time
}

type AgentScheduler struct {
	pq      *priorityQueue
	maxConc int
	sem     *semaphore.Weighted
	running map[uint]*AnalysisTask
	mu      sync.Mutex
	stopCh  chan struct{}
}

func NewAgentScheduler(maxConcurrency int) *AgentScheduler {
	pq := &priorityQueue{}
	heap.Init(pq)
	return &AgentScheduler{
		pq:      pq,
		maxConc: maxConcurrency,
		sem:     semaphore.NewWeighted(int64(maxConcurrency)),
		running: make(map[uint]*AnalysisTask),
		stopCh:  make(chan struct{}),
	}
}

func (s *AgentScheduler) Submit(task *AnalysisTask) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if _, exists := s.running[task.DefectID]; exists {
		return fmt.Errorf("defect %d already has a running analysis", task.DefectID)
	}

	for _, item := range s.pq.items {
		if item.DefectID == task.DefectID {
			return fmt.Errorf("defect %d already in queue", task.DefectID)
		}
	}

	task.SubmittedAt = time.Now()
	heap.Push(s.pq, task)
	logger.Infof("[Scheduler] task %s submitted, defect=%d priority=%d queue_len=%d",
		task.ID, task.DefectID, task.Priority, s.pq.Len())

	return nil
}

func (s *AgentScheduler) Cancel(defectID uint) bool {
	s.mu.Lock()
	defer s.mu.Unlock()

	if task, exists := s.running[defectID]; exists {
		task.Cancel()
		delete(s.running, defectID)
		logger.Infof("[Scheduler] cancelled running task %s for defect %d", task.ID, defectID)
		return true
	}

	for i, item := range s.pq.items {
		if item.DefectID == defectID {
			heap.Remove(s.pq, i)
			logger.Infof("[Scheduler] removed queued task %s for defect %d", item.ID, defectID)
			return true
		}
	}

	return false
}

func (s *AgentScheduler) QueueStatus() []TaskStatusInfo {
	s.mu.Lock()
	defer s.mu.Unlock()

	var result []TaskStatusInfo

	for _, item := range s.pq.items {
		result = append(result, TaskStatusInfo{
			TaskID:      item.ID,
			DefectID:    item.DefectID,
			Priority:    item.Priority,
			Status:      TaskStatusQueued,
			SubmittedAt: item.SubmittedAt,
		})
	}

	for _, task := range s.running {
		result = append(result, TaskStatusInfo{
			TaskID:      task.ID,
			DefectID:    task.DefectID,
			Priority:    task.Priority,
			Status:      TaskStatusRunning,
			SubmittedAt: task.SubmittedAt,
		})
	}

	return result
}

func (s *AgentScheduler) Start(dispatchCtx context.Context, executeFunc func(ctx context.Context, task *AnalysisTask) *AnalysisResult) {
	go func() {
		for {
			select {
			case <-dispatchCtx.Done():
				return
			case <-s.stopCh:
				return
			default:
			}

			if err := s.sem.Acquire(dispatchCtx, 1); err != nil {
				return
			}

			s.mu.Lock()
			if s.pq.Len() == 0 {
				s.mu.Unlock()
				s.sem.Release(1)
				time.Sleep(100 * time.Millisecond)
				continue
			}
			task := heap.Pop(s.pq).(*AnalysisTask)
			s.running[task.DefectID] = task
			s.mu.Unlock()

			go func(t *AnalysisTask) {
				defer s.sem.Release(1)
				defer func() {
					s.mu.Lock()
					delete(s.running, t.DefectID)
					s.mu.Unlock()
				}()

				result := executeFunc(t.Ctx, t)
				if t.ResultCh != nil {
					select {
					case t.ResultCh <- result:
					default:
					}
				}
			}(task)
		}
	}()
}

func (s *AgentScheduler) Stop() {
	close(s.stopCh)
	s.mu.Lock()
	for _, task := range s.running {
		task.Cancel()
	}
	s.running = make(map[uint]*AnalysisTask)
	s.mu.Unlock()
}

type priorityQueue struct {
	items []*AnalysisTask
}

func (pq *priorityQueue) Len() int { return len(pq.items) }

func (pq *priorityQueue) Less(i, j int) bool {
	if pq.items[i].Priority != pq.items[j].Priority {
		return pq.items[i].Priority < pq.items[j].Priority
	}
	return pq.items[i].SubmittedAt.Before(pq.items[j].SubmittedAt)
}

func (pq *priorityQueue) Swap(i, j int) {
	pq.items[i], pq.items[j] = pq.items[j], pq.items[i]
}

func (pq *priorityQueue) Push(x interface{}) {
	pq.items = append(pq.items, x.(*AnalysisTask))
}

func (pq *priorityQueue) Pop() interface{} {
	old := pq.items
	n := len(old)
	item := old[n-1]
	pq.items = old[:n-1]
	return item
}
