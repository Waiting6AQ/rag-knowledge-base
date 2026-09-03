# 多阶段构建：阶段1 用 Node 打包 Vue，阶段2 用 nginx 托管静态文件 + 代理 API
# 阶段1：构建
FROM node:20 AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# 阶段2：运行（nginx）
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
