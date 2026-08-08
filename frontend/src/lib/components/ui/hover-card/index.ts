// shadcn-svelte's hover card. `bits-ui` calls the primitive `LinkPreview`; the
// component is the same thing under the name the rest of the ecosystem uses,
// and unlike a popover it opens on hover *and* on keyboard focus, which is what
// makes it usable for an annotation rather than a control.
import { LinkPreview as HoverCardPrimitive } from 'bits-ui';
import Content from './hover-card-content.svelte';

const Root = HoverCardPrimitive.Root;
const Trigger = HoverCardPrimitive.Trigger;

export {
  Root,
  Content,
  Trigger,
  //
  Root as HoverCard,
  Content as HoverCardContent,
  Trigger as HoverCardTrigger
};
