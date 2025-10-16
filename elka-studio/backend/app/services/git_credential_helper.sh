#!/bin/sh
# A simple Git credential helper

# Git will call this script with a series of key=value pairs on stdin.
# We only care about the host.
while read -r line; do
  if [ "$(echo "$line" | cut -d '=' -f 1)" = "host" ]; then
    eval "$line"
  fi
done

# Based on the host, we output the credentials.
# "oauth2" is the standard username for token-based auth on GitHub.
echo "username=oauth2"
echo "password=$GIT_TOKEN"
