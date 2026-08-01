<script setup>
defineProps({
  items: { type: Array, required: true }
})
</script>

<template>
  <div class="kpi-bar">
    <div v-for="(item, i) in items" :key="i" class="kpi-cell">
      <div class="kpi-label">{{ item.label }}</div>
      <div class="kpi-value" :class="item.color || ''">{{ item.value }}</div>
      <div v-if="item.note" class="kpi-note">{{ item.note }}</div>
    </div>
  </div>
</template>
