package com.ragadmin.common;

import lombok.AllArgsConstructor;
import lombok.Data;

import java.util.List;

/**
 * 分页响应结构：{total 总数, list 当前页数据}
 * 前端分页器需要 total 才能算总页数
 */
@Data
@AllArgsConstructor
public class PageResult<T> {

    private long total;
    private List<T> list;
}
