#!/bin/sh
echo "$@"
if [[ "$1" == "serve" ]]; then
    echo "starting server on http://localhost:1313"
    hugo server --bind=0.0.0.0 --baseURL=http://0.0.0.0:1313 --disableFastRender
else
    echo "Invalid command"
fi
