# Unprivileged nginx: runs as UID 101 and listens on 8080.
FROM nginxinc/nginx-unprivileged:1.27.5-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html

USER 101

EXPOSE 8080
