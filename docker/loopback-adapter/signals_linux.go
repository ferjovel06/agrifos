package main

import (
	"os"
	"os/signal"
	"syscall"
)

func forwardSignals(child *os.Process) func() {
	signals := make(chan os.Signal, 4)
	done := make(chan struct{})
	signal.Notify(signals, syscall.SIGINT, syscall.SIGTERM, syscall.SIGHUP)
	go func() {
		for {
			select {
			case s := <-signals:
				_ = child.Signal(s)
			case <-done:
				return
			}
		}
	}()
	return func() { signal.Stop(signals); close(done) }
}
