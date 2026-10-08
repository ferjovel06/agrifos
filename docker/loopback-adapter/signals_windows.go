package main

import "os"

// The native Docker child shares the Windows console/process group and receives
// its console control events directly. Do not translate them into Unix signals.
func forwardSignals(child *os.Process) func() { return func() {} }
