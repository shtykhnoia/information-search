set -eu
cp /etc/wsl.conf /mnt/d/IR/.work/wsl.conf.before-docker
printf '\n[network]\ngenerateResolvConf=false\n' >> /etc/wsl.conf
