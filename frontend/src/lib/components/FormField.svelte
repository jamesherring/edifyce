<script lang="ts">
  import { Input } from '$lib/components/ui/input';
  import { Label } from '$lib/components/ui/label';

  type Props = {
    label: string;
    id?: string;
    value?: string;
    placeholder?: string;
    maxlength?: number;
    disabled?: boolean;
  };

  let { label, id, value = $bindable(''), placeholder, maxlength, disabled }: Props = $props();
</script>

<div class="space-y-2">
  <Label for={id}>{label}</Label>
  <Input {id} bind:value {placeholder} {maxlength} {disabled} />
</div>
