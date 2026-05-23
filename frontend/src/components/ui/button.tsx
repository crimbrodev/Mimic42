import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const buttonVariants = cva(
  [
    'inline-flex items-center justify-center gap-2',
    'font-mono text-sm font-medium',
    'rounded-sm border',
    'transition-all duration-150 ease-spring',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-plasma-500 focus-visible:ring-offset-2 focus-visible:ring-offset-void-900',
    'disabled:pointer-events-none disabled:opacity-40',
    'active:scale-[0.97]',
    'select-none',
  ],
  {
    variants: {
      variant: {
        default: [
          'bg-plasma-600 border-plasma-500 text-white',
          'hover:bg-plasma-500 hover:shadow-plasma-sm hover:border-plasma-400',
        ],
        secondary: [
          'bg-void-700 border-void-600 text-void-100',
          'hover:bg-void-600 hover:border-void-500',
        ],
        ghost: [
          'bg-transparent border-transparent text-void-300',
          'hover:bg-void-800 hover:border-void-700 hover:text-void-100',
        ],
        danger: [
          'bg-crimson-700 border-crimson-600 text-white',
          'hover:bg-crimson-600 hover:shadow-crimson hover:border-crimson-500',
        ],
        success: [
          'bg-neon-700 border-neon-600 text-white',
          'hover:bg-neon-600 hover:shadow-neon-sm',
        ],
        outline: [
          'bg-transparent border-void-600 text-void-200',
          'hover:bg-void-800 hover:border-plasma-600 hover:text-plasma-400',
        ],
        'plasma-outline': [
          'bg-transparent border-plasma-700 text-plasma-400',
          'hover:bg-plasma-950 hover:border-plasma-500 hover:text-plasma-300',
          'hover:shadow-plasma-sm',
        ],
      },
      size: {
        xs: 'h-6 px-2 text-xs',
        sm: 'h-8 px-3 text-xs',
        md: 'h-9 px-4',
        lg: 'h-11 px-6 text-base',
        xl: 'h-13 px-8 text-base',
        icon: 'h-9 w-9 p-0',
        'icon-sm': 'h-7 w-7 p-0',
        'icon-lg': 'h-11 w-11 p-0',
      },
      loading: {
        true: 'cursor-wait',
        false: '',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'md',
      loading: false,
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  isLoading?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

const Spinner = ({ className }: { className?: string }) => (
  <svg
    className={cn('animate-spin', className)}
    xmlns="http://www.w3.org/2000/svg"
    fill="none"
    viewBox="0 0 24 24"
    aria-hidden="true"
  >
    <circle
      className="opacity-25"
      cx="12"
      cy="12"
      r="10"
      stroke="currentColor"
      strokeWidth="4"
    />
    <path
      className="opacity-75"
      fill="currentColor"
      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
    />
  </svg>
);

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant,
      size,
      isLoading,
      loading: _loading,
      leftIcon,
      rightIcon,
      children,
      disabled,
      ...props
    },
    ref
  ) => {
    const isDisabled = disabled || isLoading;

    return (
      <button
        ref={ref}
        className={cn(
          buttonVariants({ variant, size, loading: isLoading }),
          className
        )}
        disabled={isDisabled}
        aria-disabled={isDisabled}
        {...props}
      >
        {isLoading ? (
          <Spinner className="h-4 w-4" />
        ) : leftIcon ? (
          <span className="shrink-0">{leftIcon}</span>
        ) : null}
        {children}
        {!isLoading && rightIcon ? (
          <span className="shrink-0">{rightIcon}</span>
        ) : null}
      </button>
    );
  }
);

Button.displayName = 'Button';

export { Button, buttonVariants };
