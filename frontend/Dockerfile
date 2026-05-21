FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.d/99-access-config.sh
RUN sed -i 's/\r$//' /docker-entrypoint.d/99-access-config.sh \
    && chmod +x /docker-entrypoint.d/99-access-config.sh

COPY . /usr/share/nginx/html

EXPOSE 80
