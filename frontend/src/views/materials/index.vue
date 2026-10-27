<script setup lang="ts">
import ModulePlaceholder from "@/components/ModulePlaceholder.vue";
</script>

<template>
  <ModulePlaceholder
    title="素材资产管理库"
    description="图片、视频、文案、封面、音频集中存放，分类打标、全文检索、版本管理，创作时直接选用。告别散落在网盘与聊天记录里的文件，让素材成为可复用的内容资产。"
    :features="[
      '素材分类：图片 / 视频 / 文案 / 封面 / 音频',
      '标签管理与全文检索',
      '批量上传、分片上传与预览',
      '素材版本管理与缩略图生成',
      '创作编辑器内直接选用素材',
      'MD5 去重与存储空间统计',
    ]"
  />
</template>
