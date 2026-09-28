<template>
  <div class="input-area">
    <input
      :value="modelValue"
      :placeholder="placeholder"
      :disabled="disabled"
      @input="$emit('update:modelValue', $event.target.value)"
      @keydown.enter="$emit('send')"
    />
    <button :disabled="disabled" title="发送" @click="$emit('send')">➤</button>
  </div>
</template>

<script setup>
defineProps({
  modelValue: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  placeholder: { type: String, default: '输入你的问题...' },
})

defineEmits(['update:modelValue', 'send'])
</script>
