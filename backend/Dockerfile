# 多阶段构建：阶段1 用 Maven 打包，阶段2 只带 JRE（镜像小）
# 阶段1：构建
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /app
COPY pom.xml .
RUN mvn dependency:go-offline -B
COPY src ./src
RUN mvn package -DskipTests -B

# 阶段2：运行（仅 JRE，约 250MB）
FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /app/target/*.jar app.jar
EXPOSE 8081
ENV DB_PASSWORD=""
ENV JWT_SECRET=""
# 容器内通过环境变量注入配置（compose 传入），不依赖 .env 文件
ENTRYPOINT ["java", "-jar", "app.jar"]
