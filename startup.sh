#!/bin/sh
echo "$@"
if [[ "$1" == "serve" ]]; then
    echo "starting server on http://localhost:1313"
    hugo server --bind=0.0.0.0 --baseURL=http://0.0.0.0:1313 --disableFastRender
elif [[ "$1" == "new-post" ]]; then
    TITLE="${2:-my-new-post}"
    hugo new content "blog/${TITLE}.md"
    echo "Created new post: content/blog/${TITLE}.md"
else
    echo "Invalid command"
fi
