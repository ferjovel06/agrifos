// The adapter is placed on PATH only for the pinned Supabase CLI child process.
// It forwards native argv/stdio/environment, without a shell or a Docker socket.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const marker = "com.agrifos.loopback-adapter"

var revision = "development"
var denied = errors.New("loopback adapter rejected unsafe or unsupported Docker arguments")
var projectPattern = regexp.MustCompile(`^agrifos(-it-[0-9a-f]{8})?$`)

type scope struct{ project, network, workdir string }

func (s scope) valid() bool {
	return projectPattern.MatchString(s.project) && filepath.IsAbs(s.workdir) &&
		((s.project == "agrifos" && s.network == "agrifos-local") ||
			(s.project != "agrifos" && s.network == s.project))
}
func normalized(s string) string {
	s = strings.TrimRight(strings.ReplaceAll(s, `\`, "/"), "/")
	if len(s) > 1 && s[1] == ':' {
		s = strings.ToLower(s)
	}
	return s
}
func (s scope) owns(labels map[string]string) bool {
	if labels["com.supabase.cli.project"] == s.project &&
		normalized(labels["com.supabase.cli.workdir"]) == normalized(s.workdir) {
		return true
	}
	return labels["com.agrifos.managed-by"] == "supabase-local.sh" &&
		labels["com.agrifos.project"] == s.project && labels["com.agrifos.probe-token"] != ""
}

func portNumber(value string, zero bool) bool {
	if value == "" {
		return false
	}
	for _, c := range value {
		if c < '0' || c > '9' {
			return false
		}
	}
	n, err := strconv.Atoi(value)
	return err == nil && n <= 65535 && (n > 0 || (zero && n == 0))
}
func loopbackPort(value string) (string, error) {
	parts := strings.Split(value, "/")
	if len(parts) > 2 || (len(parts) == 2 && parts[1] != "tcp" && parts[1] != "udp") {
		return "", denied
	}
	ports := strings.Split(parts[0], ":")
	host, container := "0", ""
	switch len(ports) {
	case 1:
		container = ports[0]
	case 2:
		host, container = ports[0], ports[1]
	case 3:
		if ports[0] != "127.0.0.1" {
			return "", denied
		}
		host, container = ports[1], ports[2]
	default:
		return "", denied
	}
	if !portNumber(host, true) || !portNumber(container, false) {
		return "", denied
	}
	result := "127.0.0.1:" + host + ":" + container
	if len(parts) == 2 {
		result += "/" + parts[1]
	}
	return result, nil
}

// An explicit flag vocabulary avoids interpreting container command arguments
// as Docker flags. Unknown options fail before creation, rather than guessing.
var valueFlags = map[string]bool{
	"--name": true, "--hostname": true, "--env": true, "-e": true,
	"--volume": true, "-v": true, "--volumes-from": true, "--tmpfs": true,
	"--publish": true, "-p": true, "--expose": true, "--network": true,
	"--network-alias": true, "--label": true, "-l": true, "--entrypoint": true,
	"--restart": true, "--security-opt": true, "--add-host": true,
	"--health-cmd": true, "--health-interval": true, "--health-retries": true,
	"--health-start-period": true, "--health-start-interval": true, "--health-timeout": true,
	"--workdir": true, "-w": true, "--user": true, "-u": true, "--platform": true,
}
var boolFlags = map[string]bool{"--rm": true, "--interactive": true, "-i": true, "--detach": true, "-d": true, "--no-healthcheck": true}

func command(args []string) (string, int) {
	if len(args) == 0 {
		return "", 0
	}
	if args[0] == "container" && len(args) > 1 {
		return args[1], 2
	}
	return args[0], 1
}
func rewrite(args []string, s scope) ([]string, error) {
	if len(args) > 0 && strings.HasPrefix(args[0], "-") && args[0] != "--version" {
		return nil, denied
	}
	verb, offset := command(args)
	if verb != "create" && verb != "run" {
		return args, nil
	}
	labels := map[string]string{}
	network := ""
	ports := 0
	binds := false
	out := append([]string{}, args[:offset]...)
	imageIndex := -1
	for i := offset; i < len(args); i++ {
		flag := args[i]
		if !strings.HasPrefix(flag, "-") {
			imageIndex = i
			break
		}
		name, value, inline := strings.Cut(flag, "=")
		if boolFlags[name] {
			if inline && value != "true" && value != "false" {
				return nil, denied
			}
			out = append(out, flag)
			continue
		}
		if !valueFlags[name] {
			return nil, denied
		}
		if !inline {
			i++
			if i >= len(args) {
				return nil, denied
			}
			value = args[i]
		}
		switch name {
		case "--volume", "-v", "--volumes-from":
			binds = true
		case "--publish", "-p":
			var err error
			value, err = loopbackPort(value)
			if err != nil {
				return nil, err
			}
			ports++
		case "--label", "-l":
			key, val, ok := strings.Cut(value, "=")
			if !ok || key == marker {
				return nil, denied
			}
			if _, duplicate := labels[key]; duplicate {
				return nil, denied
			}
			labels[key] = val
		case "--network":
			if network != "" {
				return nil, denied
			}
			network = value
		}
		out = append(out, name, value)
	}
	// CLI 2.120's ephemeral initial-schema jobs omit the workdir label.
	// Admit that exact project/Compose-label form only without binds or ports,
	// on the already-owned bridge, and attach the selected workdir ourselves.
	if verb == "run" && labels["com.supabase.cli.workdir"] == "" &&
		labels["com.supabase.cli.project"] == s.project &&
		labels["com.docker.compose.project"] == s.project && !binds && ports == 0 {
		labels["com.supabase.cli.workdir"] = s.workdir
		out = append(out, "--label", "com.supabase.cli.workdir="+s.workdir)
	}
	if imageIndex < 0 || !s.owns(labels) || network != s.network {
		return nil, denied
	}
	// Services use create/cp/start. One-shot CLI run jobs must publish no ports.
	if verb == "run" && ports != 0 {
		return nil, denied
	}
	out = append(out, "--label", marker+"="+revision)
	out = append(out, args[imageIndex:]...)
	return out, nil
}

type binding struct {
	HostIP   string `json:"HostIp"`
	HostPort string
}
type container struct {
	Config     struct{ Labels map[string]string }
	HostConfig struct {
		NetworkMode     string
		PublishAllPorts bool
		PortBindings    map[string][]binding
	}
	NetworkSettings struct{ Ports map[string][]binding }
}

func safeContainer(data []byte, s scope, after bool) error {
	var items []container
	if json.Unmarshal(data, &items) != nil || len(items) != 1 {
		return denied
	}
	c := items[0]
	if !s.owns(c.Config.Labels) || c.Config.Labels[marker] == "" ||
		c.HostConfig.NetworkMode != s.network || c.HostConfig.PublishAllPorts {
		return denied
	}
	maps := []map[string][]binding{c.HostConfig.PortBindings}
	if after {
		maps = append(maps, c.NetworkSettings.Ports)
	}
	for i, ports := range maps {
		for _, entries := range ports {
			for _, b := range entries {
				if b.HostIP != "127.0.0.1" || !portNumber(b.HostPort, i == 0) {
					return denied
				}
			}
		}
	}
	if after {
		for port, requested := range c.HostConfig.PortBindings {
			if len(requested) > 0 && len(c.NetworkSettings.Ports[port]) == 0 {
				return denied
			}
		}
	}
	return nil
}
func activationTargets(args []string) ([]string, error) {
	verb, offset := command(args)
	if verb != "start" && verb != "restart" {
		return nil, nil
	}
	targets := []string{}
	for i := offset; i < len(args); i++ {
		arg := args[i]
		if arg == "--" {
			targets = append(targets, args[i+1:]...)
			break
		}
		if strings.HasPrefix(arg, "-") {
			return nil, denied
		}
		if arg == "" {
			return nil, denied
		}
		targets = append(targets, arg)
	}
	if len(targets) == 0 {
		return nil, denied
	}
	return targets, nil
}
func inspect(real, target string, s scope, after bool) error {
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	// Capture only the fields needed for safety; never inspect/log container Env.
	format := `[{"Config":{"Labels":{{json .Config.Labels}}},"HostConfig":{"NetworkMode":{{json .HostConfig.NetworkMode}},"PublishAllPorts":{{json .HostConfig.PublishAllPorts}},"PortBindings":{{json .HostConfig.PortBindings}}},"NetworkSettings":{"Ports":{{json .NetworkSettings.Ports}}}}]`
	data, err := exec.CommandContext(ctx, real, "inspect", "--format", format, target).Output()
	if err != nil {
		return denied
	}
	return safeContainer(data, s, after)
}
func run() int {
	args := os.Args[1:]
	if len(args) == 1 && args[0] == "--agrifos-adapter-version" {
		fmt.Println(revision)
		return 0
	}
	s := scope{os.Getenv("AGRIFOS_ADAPTER_PROJECT"), os.Getenv("AGRIFOS_ADAPTER_NETWORK"), os.Getenv("AGRIFOS_ADAPTER_WORKDIR")}
	real := os.Getenv("AGRIFOS_REAL_DOCKER")
	self, _ := os.Executable()
	if !s.valid() || !filepath.IsAbs(real) || normalized(real) == normalized(self) {
		fmt.Fprintln(os.Stderr, "loopback adapter requires a valid local project and absolute native Docker path")
		return 125
	}
	rewritten, err := rewrite(args, s)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 125
	}
	targets, err := activationTargets(args)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 125
	}
	for _, target := range targets {
		if inspect(real, target, s, false) != nil {
			fmt.Fprintln(os.Stderr, "loopback adapter refused activation before Docker start; inspect ownership and requested bindings")
			return 125
		}
	}
	child := exec.Command(real, rewritten...)
	child.Stdin, child.Stdout, child.Stderr = os.Stdin, os.Stdout, os.Stderr
	if err = child.Start(); err != nil {
		fmt.Fprintln(os.Stderr, "loopback adapter could not start native Docker")
		return 125
	}
	stopSignals := forwardSignals(child.Process)
	defer stopSignals()
	if err = child.Wait(); err != nil {
		if e, ok := err.(*exec.ExitError); ok {
			return e.ExitCode()
		}
		return 125
	}
	for _, target := range targets {
		if inspect(real, target, s, true) != nil {
			// A daemon returning unexpected actual bindings must stop this owned
			// container. Pre-start ownership was verified; no unrelated cleanup.
			ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
			_ = exec.CommandContext(ctx, real, "stop", "--time", "1", target).Run()
			cancel()
			fmt.Fprintln(os.Stderr, "loopback adapter failed post-start binding verification; owned container stop attempted")
			return 125
		}
	}
	return 0
}
func main() { os.Exit(run()) }
