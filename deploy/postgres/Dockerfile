FROM golang:1.26-alpine AS gosu-build
ARG GOSU_VERSION=1.19
RUN apk add --no-cache git
RUN git clone --depth 1 --branch "$GOSU_VERSION" https://github.com/tianon/gosu.git /src
WORKDIR /src
# Rebuild the same upstream helper with a patched Go standard library.
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-d -w" -o /gosu .

FROM postgres:17-alpine
RUN apk upgrade --no-cache
COPY --from=gosu-build /gosu /usr/local/bin/gosu
RUN gosu nobody id
