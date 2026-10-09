package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func fixtureScope() scope {
	return scope{"agrifos-it-1234abcd", "agrifos-it-1234abcd", filepath.Join(os.TempDir(), "repo", ".docker", "integration", "agrifos-it-1234abcd")}
}
func createArgs(extra ...string) []string {
	s := fixtureScope()
	args := []string{"create", "--network", s.network,
		"--label", "com.supabase.cli.project=" + s.project,
		"--label", "com.supabase.cli.workdir=" + s.workdir}
	return append(append(args, extra...), "image", "-p", "container-command-argument")
}
func TestPortFormats(t *testing.T) {
	for input, expected := range map[string]string{
		"54321:8000": "127.0.0.1:54321:8000", "0:8080": "127.0.0.1:0:8080",
		"8080": "127.0.0.1:0:8080", "127.0.0.1:1234:80/udp": "127.0.0.1:1234:80/udp",
	} {
		t.Run(input, func(t *testing.T) {
			actual, err := loopbackPort(input)
			if err != nil || actual != expected {
				t.Fatalf("unexpected binding %q", actual)
			}
		})
	}
	for _, input := range []string{"0.0.0.0:80:80", "[::]:80:80", "[::1]:80:80", "localhost:80:80", "192.168.1.5:80:80", "65536:80", "0:0", ":80", "80-90:80-90", "80:80/sctp", "80:80/tcp/udp", "-1:80", "8x:80"} {
		t.Run("reject-"+input, func(t *testing.T) {
			if _, err := loopbackPort(input); err == nil {
				t.Fatal("unsafe binding accepted")
			}
		})
	}
}
func TestRewritesBeforeImageOnly(t *testing.T) {
	for _, flags := range [][]string{{"-p", "54321:8000"}, {"--publish=54321:8000"}, {"-p=54321:8000"}, {"--publish", "54321:8000"}} {
		out, err := rewrite(createArgs(flags...), fixtureScope())
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(strings.Join(out, " "), "127.0.0.1:54321:8000") {
			t.Fatal("binding missing")
		}
		if !reflect.DeepEqual(out[len(out)-3:], []string{"image", "-p", "container-command-argument"}) {
			t.Fatal("container command changed")
		}
	}
}
func TestRejectsUnsafeCreation(t *testing.T) {
	for _, flags := range [][]string{{"-P"}, {"--publish-all"}, {"--network", "host"}, {"--network=other"}, {"--label", "com.supabase.cli.project=other"}, {"--label", marker + "=spoof"}, {"--privileged"}, {"--unknown", "anything"}, {"-p80:80"}, {"-p", "0.0.0.0:80:80"}} {
		if _, err := rewrite(createArgs(flags...), fixtureScope()); err == nil {
			t.Fatalf("unsafe flags accepted: %q", flags)
		}
	}
	if _, err := rewrite([]string{"create", "--network", fixtureScope().network, "image"}, fixtureScope()); err == nil {
		t.Fatal("foreign creation accepted")
	}
	if _, err := rewrite(createArgs("--label", "missing-equals"), fixtureScope()); err == nil {
		t.Fatal("invalid label accepted")
	}
}
func TestContainerAliasAndPassthrough(t *testing.T) {
	if _, err := rewrite([]string{"--context", "other", "create", "image"}, fixtureScope()); err == nil {
		t.Fatal("global option bypass accepted")
	}
	args := append([]string{"container"}, createArgs("-p", "80:80")...)
	if _, err := rewrite(args, fixtureScope()); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{{"inspect", "anything"}, {"cp", "-", "owned:/tmp"}, {"info"}, {"ps", "-a"}, {"pull", "image"}} {
		out, err := rewrite(args, fixtureScope())
		if err != nil || !reflect.DeepEqual(out, args) {
			t.Fatal("passthrough changed")
		}
	}
}
func TestRunJobsCannotPublish(t *testing.T) {
	args := createArgs()
	args[0] = "run"
	if _, err := rewrite(args, fixtureScope()); err != nil {
		t.Fatal(err)
	}
	args = createArgs("-p", "80:80")
	args[0] = "run"
	if _, err := rewrite(args, fixtureScope()); err == nil {
		t.Fatal("run published ports")
	}
}

func TestCliInitialSchemaJobRequiresOwnedLabelsWithoutBindsOrPorts(t *testing.T) {
	s := fixtureScope()
	args := []string{"run", "--rm", "--network", s.network, "--label", "com.supabase.cli.project=" + s.project,
		"--label", "com.docker.compose.project=" + s.project, "image", "migrate"}
	if _, err := rewrite(args, s); err != nil {
		t.Fatal(err)
	}
	for _, extra := range [][]string{{"-v", "/foreign:/data"}, {"-p", "80:80"}} {
		bad := append(append(append([]string{}, args[:len(args)-2]...), extra...), "image")
		if _, err := rewrite(bad, s); err == nil {
			t.Fatal("unscoped migration accepted")
		}
	}
}
func fixtureContainer() container {
	s := fixtureScope()
	var c container
	c.Config.Labels = map[string]string{"com.supabase.cli.project": s.project, "com.supabase.cli.workdir": s.workdir, marker: "test"}
	c.HostConfig.NetworkMode = s.network
	c.HostConfig.PortBindings = map[string][]binding{"80/tcp": {{"127.0.0.1", "0"}}}
	c.NetworkSettings.Ports = map[string][]binding{"80/tcp": {{"127.0.0.1", "32768"}}}
	return c
}
func check(c container, after bool) error {
	data, _ := json.Marshal([]container{c})
	return safeContainer(data, fixtureScope(), after)
}
func TestPreStartRejectsUnsafeAndForeignContainers(t *testing.T) {
	mutations := []func(*container){
		func(c *container) { c.Config.Labels["com.supabase.cli.project"] = "other" },
		func(c *container) { c.Config.Labels["com.supabase.cli.workdir"] = "/foreign" },
		func(c *container) { delete(c.Config.Labels, marker) },
		func(c *container) { c.HostConfig.NetworkMode = "host" },
		func(c *container) { c.HostConfig.PublishAllPorts = true },
		func(c *container) { c.HostConfig.PortBindings["80/tcp"] = []binding{{"", "80"}} },
		func(c *container) { c.HostConfig.PortBindings["80/tcp"] = []binding{{"0.0.0.0", "80"}} },
		func(c *container) { c.HostConfig.PortBindings["80/tcp"] = []binding{{"::", "80"}} },
	}
	for _, mutate := range mutations {
		c := fixtureContainer()
		mutate(&c)
		if check(c, false) == nil {
			t.Fatal("unsafe pre-start metadata accepted")
		}
	}
	if check(fixtureContainer(), false) != nil {
		t.Fatal("valid pre-start rejected")
	}
}
func TestPostStartChecksActualBindings(t *testing.T) {
	if check(fixtureContainer(), true) != nil {
		t.Fatal("valid ephemeral binding rejected")
	}
	for _, entries := range [][]binding{nil, {{"0.0.0.0", "80"}}, {{"127.0.0.1", "80"}, {"::", "80"}}, {{"127.0.0.1", "0"}}} {
		c := fixtureContainer()
		c.NetworkSettings.Ports["80/tcp"] = entries
		if check(c, true) == nil {
			t.Fatal("unsafe actual binding accepted")
		}
	}
	if safeContainer([]byte("not-json"), fixtureScope(), false) == nil {
		t.Fatal("invalid inspect accepted")
	}
	if safeContainer([]byte("[]"), fixtureScope(), false) == nil {
		t.Fatal("empty inspect accepted")
	}
}
func TestActivationChecksEveryTarget(t *testing.T) {
	targets, err := activationTargets([]string{"container", "start", "first", "second"})
	if err != nil || !reflect.DeepEqual(targets, []string{"first", "second"}) {
		t.Fatal("target parsing failed")
	}
	for _, args := range [][]string{{"start"}, {"restart", "--unknown", "first"}, {"start", ""}} {
		if _, err := activationTargets(args); err == nil {
			t.Fatal("unsafe activation accepted")
		}
	}
}
func TestScopeIsolation(t *testing.T) {
	if !fixtureScope().valid() {
		t.Fatal("valid integration scope rejected")
	}
	for _, s := range []scope{{"other", "other", "/repo"}, {"agrifos", "host", "/repo"}, {"agrifos-it-ABCDEF12", "agrifos-it-ABCDEF12", "/repo"}, {"agrifos", "agrifos-local", "relative"}} {
		if s.valid() {
			t.Fatal("invalid scope accepted")
		}
	}
	if !fixtureScope().owns(map[string]string{"com.agrifos.managed-by": "supabase-local.sh", "com.agrifos.project": fixtureScope().project, "com.agrifos.probe-token": "unique"}) {
		t.Fatal("owned preflight rejected")
	}
}
