<script setup lang="ts">
defineProps<{ primary?: boolean; busy?: boolean }>();
</script>
<template>
  <button
    type="button"
    :class="['button', { 'button-primary': primary }]"
    :disabled="busy"
    :aria-busy="busy"
  >
    <slot />
  </button>
</template>
