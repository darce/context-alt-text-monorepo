import * as React from 'react';
import { Check, ChevronsUpDown } from 'lucide-react';
import { Command as CommandPrimitive } from 'cmdk';
import * as PopoverPrimitive from '@radix-ui/react-popover';
import { __, sprintf } from '@wordpress/i18n';

// --- Command Components (cmdk wrapper) ---

const Command = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive>
>(({ className, ...props }, ref) => (
  <CommandPrimitive ref={ref} className={`acx-combobox__command ${className ?? ''}`} {...props} />
));
Command.displayName = CommandPrimitive.displayName;

const CommandInput = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Input>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Input>
>(({ className, ...props }, ref) => (
  <div className="acx-combobox__input-wrapper" cmdk-input-wrapper="">
    <CommandPrimitive.Input ref={ref} className={`acx-combobox__input ${className ?? ''}`} {...props} />
  </div>
));
CommandInput.displayName = CommandPrimitive.Input.displayName;

const CommandList = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.List>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.List ref={ref} className={`acx-combobox__list ${className ?? ''}`} {...props} />
));
CommandList.displayName = CommandPrimitive.List.displayName;

const CommandEmpty = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Empty>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Empty>
>((props, ref) => <CommandPrimitive.Empty ref={ref} className="acx-combobox__empty" {...props} />);
CommandEmpty.displayName = CommandPrimitive.Empty.displayName;

const CommandGroup = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Group>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Group>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Group ref={ref} className={`acx-combobox__group ${className ?? ''}`} {...props} />
));
CommandGroup.displayName = CommandPrimitive.Group.displayName;

const CommandItem = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Item>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Item ref={ref} className={`acx-combobox__item ${className ?? ''}`} {...props} />
));
CommandItem.displayName = CommandPrimitive.Item.displayName;

// --- Combobox Component ---

export interface ComboboxOption {
  value: string;
  label: string;
  group?: string;
  [key: string]: unknown;
}

interface ComboboxProps {
  options: ComboboxOption[];
  value?: string;
  onSelect?: (value: string) => void;
  onValueChange?: (value: string) => void;
  placeholder?: string;
  emptyText?: string;
  emptyMessage?: string;
  className?: string;
  onCreate?: (value: string) => void;
  searchPlaceholder?: string;
  ariaLabel?: string;
  disabled?: boolean;
  isLoading?: boolean;
  renderOption?: (option: ComboboxOption) => React.ReactNode;
  id?: string;
  portalContainer?: HTMLElement | null;
}

const filterCommandOption = (value: string, search: string): number =>
  value.toLowerCase().includes(search.toLowerCase()) ? 1 : 0;

export const Combobox = ({
  options,
  value,
  onSelect,
  onValueChange,
  placeholder = __('Select option...', 'alt-context'),
  emptyText = __('No option found.', 'alt-context'),
  emptyMessage,
  className,
  onCreate,
  searchPlaceholder,
  ariaLabel,
  disabled,
  isLoading = false,
  renderOption,
  id,
  portalContainer,
}: ComboboxProps): React.ReactElement => {
  const [open, setOpen] = React.useState(false);
  const [inputValue, setInputValue] = React.useState(value ?? '');

  // Sync internal input value with external value prop if provided
  React.useEffect(() => {
    if (value !== undefined) {
      setInputValue(value);
    }
  }, [value]);

  const handleInputChange = (newValue: string) => {
    setInputValue(newValue);
    if (onValueChange) {
      onValueChange(newValue);
    }
  };

  const selectedOption = options.find((option) => option.value === value);

  // Group options with explicit ordering: "Suggested" first, then "All Labels", then others
  const groupedOptions = React.useMemo(() => {
    const groups = options.reduce(
      (acc, option) => {
        const group = option.group ?? 'Others';
        if (!acc[group]) {
          acc[group] = [];
        }
        acc[group].push(option);
        return acc;
      },
      {} as Record<string, ComboboxOption[]>,
    );

    // Define explicit group order
    const groupOrder = ['Suggested', 'All Labels', 'Others'];
    const orderedEntries: [string, ComboboxOption[]][] = [];

    // Add groups in order
    for (const groupName of groupOrder) {
      if (groups[groupName]) {
        orderedEntries.push([groupName, groups[groupName]]);
      }
    }

    // Add any other groups not in the predefined order
    for (const groupName of Object.keys(groups)) {
      if (!groupOrder.includes(groupName)) {
        orderedEntries.push([groupName, groups[groupName]]);
      }
    }

    return orderedEntries;
  }, [options]);

  const handleOpenChange = React.useCallback((isOpen: boolean) => {
    setOpen(isOpen);
    if (isOpen) {
      setInputValue('');
    }
  }, []);

  const handleSelectOption = React.useCallback(
    (option: ComboboxOption) => {
      const nextValue = option.value === value ? '' : option.value;
      onSelect?.(nextValue);
      onValueChange?.(option.label);
      setOpen(false);
    },
    [onSelect, onValueChange, value],
  );
  const handleCreateOption = React.useCallback(() => {
    if (!onCreate) {
      return;
    }
    onCreate(inputValue);
    setOpen(false);
  }, [inputValue, onCreate]);
  const triggerLabel = selectedOption?.label ?? (value && value.length > 0 ? value : placeholder);

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={handleOpenChange}>
      <PopoverPrimitive.Trigger asChild>
        <button
          id={id}
          role="combobox"
          aria-expanded={open}
          aria-label={ariaLabel}
          disabled={disabled}
          className={`acx-combobox__trigger ${className ?? ''}`}
          data-placeholder={!value}
        >
          {triggerLabel}
          <ChevronsUpDown className="acx-combobox__icon" />
        </button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal container={portalContainer ?? undefined}>
        <PopoverPrimitive.Content className="acx-combobox__content" align="start">
          <Command filter={filterCommandOption}>
            <CommandInput
              placeholder={searchPlaceholder ?? placeholder}
              value={inputValue}
              onValueChange={handleInputChange}
            />
            <CommandList>
              {isLoading && <div className="acx-combobox__empty">{__('Loading options...', 'alt-context')}</div>}
              <CommandEmpty>
                {emptyMessage ?? emptyText}
                {onCreate && inputValue && (
                  <div className="acx-combobox__create">
                    <button
                      type="button"
                      className="acx-button acx-button--small"
                      onClick={handleCreateOption}
                    >
                      {sprintf(__('Create "%s"', 'alt-context'), inputValue)}
                    </button>
                  </div>
                )}
              </CommandEmpty>
              {groupedOptions.map(([group, groupOptions]) => (
                <CommandGroup key={group} heading={group}>
                  {groupOptions.map((option) => (
                    <CommandItem
                      key={option.value}
                      value={option.label} // Use label for filtering
                      onSelect={() => handleSelectOption(option)}
                      data-selected={value === option.value}
                    >
                      <Check
                        className={`acx-combobox__check ${value === option.value ? 'acx-combobox__check--active' : ''}`}
                      />
                      {renderOption ? renderOption(option) : option.label}
                    </CommandItem>
                  ))}
                </CommandGroup>
              ))}
            </CommandList>
          </Command>
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
};
