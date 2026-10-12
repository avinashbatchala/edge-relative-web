<script setup lang="ts">
import type { Row } from "./types";
defineProps<{ direction: Row["direction"] }>();
</script>
<template>
  <span :class="['badge', direction]">{{ direction }}</span>
</template>
