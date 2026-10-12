# Static customer, handyman and ops pages, served by nginx on Cloud Run.
# API_BASE (the core-api URL) is written into config.js when the container starts.
FROM nginx:1.27-alpine
ENV PORT=8080 API_BASE=http://localhost:8000
COPY docker/default.conf.template /etc/nginx/templates/default.conf.template
COPY docker/40-config.sh /docker-entrypoint.d/40-config.sh
RUN chmod +x /docker-entrypoint.d/40-config.sh
COPY *.html *.js *.css /usr/share/nginx/html/
EXPOSE 8080
