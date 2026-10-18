import * as React from 'react';
import * as TabsPrimitive from '@radix-ui/react-tabs';

type TabsProps = React.ComponentPropsWithoutRef<typeof TabsPrimitive.Root>;
type TabsListProps = React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>;
type TabsTriggerProps = React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>;
type TabsContentProps = React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>;

export const Tabs = (props: TabsProps): React.JSX.Element => <TabsPrimitive.Root {...props} />;

export const TabsList = React.forwardRef<React.ElementRef<typeof TabsPrimitive.List>, TabsListProps>(
  ({ className = '', ...props }, ref) => (
    <TabsPrimitive.List ref={ref} className={`acx-tabs__list ${className}`.trim()} {...props} />
  ),
);
TabsList.displayName = TabsPrimitive.List.displayName;

export const TabsTrigger = React.forwardRef<React.ElementRef<typeof TabsPrimitive.Trigger>, TabsTriggerProps>(
  ({ className = '', ...props }, ref) => (
    <TabsPrimitive.Trigger ref={ref} className={`acx-tabs__trigger ${className}`.trim()} {...props} />
  ),
);
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

export const TabsContent = React.forwardRef<React.ElementRef<typeof TabsPrimitive.Content>, TabsContentProps>(
  ({ className = '', ...props }, ref) => (
    <TabsPrimitive.Content ref={ref} className={`acx-tabs__content ${className}`.trim()} {...props} />
  ),
);
TabsContent.displayName = TabsPrimitive.Content.displayName;
