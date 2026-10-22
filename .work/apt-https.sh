set -eu
kill -TERM 4200
cp /etc/apt/sources.list /mnt/d/IR/.work/apt-sources.before-docker
sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g; s|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list
