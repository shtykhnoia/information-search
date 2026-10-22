set -eu
for dns in 192.168.0.1 9.9.9.9 8.8.8.8; do
    printf 'nameserver %s\noptions timeout:1 attempts:1\n' "$dns" > /etc/resolv.conf
    echo "Testing $dns"
    if getent ahostsv4 download.docker.com; then exit 0; fi
done
exit 1
