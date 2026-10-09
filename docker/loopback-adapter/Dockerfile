# syntax=docker/dockerfile:1
FROM golang:1.27.2-bookworm@sha256:5cf287a799e6b94384bad13d16b14904c531f51ba65792237e122ce42b392f61 AS build
WORKDIR /src
COPY go.mod *.go ./
ARG SOURCE_REVISION
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOPROXY=off
RUN go test -race=false -v ./... \
    && mkdir /output \
    && GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w -X main.revision=${SOURCE_REVISION}" -o /output/docker . \
    && GOOS=windows GOARCH=amd64 go build -trimpath -ldflags="-s -w -X main.revision=${SOURCE_REVISION}" -o /output/docker.exe . \
    && GOOS=windows GOARCH=amd64 go test -c -o /output/adapter.test.exe
FROM scratch AS binaries
COPY --from=build /output/ /
USER 65532:65532
