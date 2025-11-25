import * as React from 'react';
import { Check, ChevronsUpDown } from 'lucide-react';
import { Command as CommandPrimitive } from 'cmdk';
import * as PopoverPrimitive from '@radix-ui/react-popover';

// --- Command Components (cmdk wrapper) ---

const Command = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive>
>(({ className, ...props }, ref) => (
  <CommandPrimitive ref={ref} className={`acx-combobox__command ${className || ''}`} {...props} />
));
Command.displayName = CommandPrimitive.displayName;

const CommandInput = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Input>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Input>
>(({ className, ...props }, ref) => (
  <div className="acx-combobox__input-wrapper" cmdk-input-wrapper="">
    <CommandPrimitive.Input ref={ref} className={`acx-combobox__input ${className || ''}`} {...props} />
  </div>
));
CommandInput.displayName = CommandPrimitive.Input.displayName;

const CommandList = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.List>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.List ref={ref} className={`acx-combobox__list ${className || ''}`} {...props} />
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
  <CommandPrimitive.Group ref={ref} className={`acx-combobox__group ${className || ''}`} {...props} />
));
CommandGroup.displayName = CommandPrimitive.Group.displayName;

const CommandItem = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Item>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Item ref={ref} className={`acx-combobox__item ${className || ''}`} {...props} />
));
CommandItem.displayName = CommandPrimitive.Item.displayName;

// --- Combobox Component ---

export interface ComboboxOption {
  value: string;
  label: string;
  group?: string;
  [key: string]: any;
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
}

export function Combobox({
  options,
  value,
  onSelect,
  onValueChange,
  placeholder = 'Select option...',
  emptyText = 'No option found.',
  emptyMessage,
  className,
  onCreate,
  searchPlaceholder,
  ariaLabel,
  disabled,
  renderOption,
}: ComboboxProps) {
  const [open, setOpen] = React.useState(false);
  const [inputValue, setInputValue] = React.useState(value || '');

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

  // Group options
  const groupedOptions = options.reduce((acc, option) => {
    const group = option.group || 'Others';
    if (!acc[group]) acc[group] = [];
    acc[group].push(option);
    return acc;
  }, {} as Record<string, ComboboxOption[]>);

  return (
    <PopoverPrimitive.Root
      open={open}
      onOpenChange={(isOpen) => {
        setOpen(isOpen);
        if (isOpen) {
          // Clear the input when opening to allow fresh typing
          setInputValue('');
        }
      }}
    >
      <PopoverPrimitive.Trigger asChild>
        <button
          role="combobox"
          aria-expanded={open}
          aria-label={ariaLabel}
          disabled={disabled}
          className={`acx-combobox__trigger ${className || ''}`}
          data-placeholder={!value}
        >
          {value || placeholder}
          <ChevronsUpDown className="acx-combobox__icon" />
        </button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Content className="acx-combobox__content" align="start">
        <Command
          filter={(value, search) => {
            if (value.toLowerCase().includes(search.toLowerCase())) return 1;
            return 0;
          }}
        >
          <CommandInput
            placeholder={searchPlaceholder || placeholder}
            value={inputValue}
            onValueChange={handleInputChange}
          />
          <CommandList>
            <CommandEmpty>
              {emptyMessage || emptyText}
              {onCreate && inputValue && (
                <div className="acx-combobox__create">
                  <button
                    className="acx-button acx-button--small"
                    onClick={() => {
                      onCreate(inputValue);
                      setOpen(false);
                    }}
                  >
                    Create "{inputValue}"
                  </button>
                </div>
              )}
            </CommandEmpty>
            {Object.entries(groupedOptions).map(([group, groupOptions]) => (
              <CommandGroup key={group} heading={group}>
                {groupOptions.map((option) => (
                  <CommandItem
                    key={option.value}
                    value={option.label} // Use label for filtering
                    onSelect={() => {
                      const nextValue = option.value === value ? '' : option.value;
                      if (onSelect) onSelect(nextValue);
                      if (onValueChange) onValueChange(option.label); // Update text input with label
                      setOpen(false);
                    }}
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
    </PopoverPrimitive.Root>
  );
}
