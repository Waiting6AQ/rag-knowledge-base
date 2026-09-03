package com.ragadmin;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
@MapperScan("com.ragadmin.mapper")
public class RagAdminApplication {

    public static void main(String[] args) {
        SpringApplication.run(RagAdminApplication.class, args);
    }
}
