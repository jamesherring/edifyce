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
    /** True when the field holds notation: renders it monospaced and makes it a
     *  target for the enclosing sheet's symbol palette. */
    notation?: boolean;
  };

  let {
    label,
    id,
    value = $bindable(''),
    placeholder,
    maxlength,
    disabled,
    notation = false
  }: Props = $props();
</script>

<div class="space-y-2">
  <Label for={id}>{label}</Label>
  <Input
    {id}
    bind:value
    {placeholder}
    {maxlength}
    {disabled}
    class={notation ? 'font-mono' : undefined}
    data-symbol-field={notation ? '' : undefined}
  />
</div>
