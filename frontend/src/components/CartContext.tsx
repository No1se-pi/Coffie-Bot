import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { createIdempotencyKey } from "../api/client";
import type { CartLineDraft, MenuItem } from "../api/types";

const STORAGE_KEY = "coffie.cart.v2";

export interface CartItem extends CartLineDraft {
  name: string;
  image_url?: string | null;
  unit_estimate_minor: number;
  modifier_names: string[];
}

interface CartValue {
  items: CartItem[];
  count: number;
  add: (
    item: MenuItem,
    modifiers: Array<{
      option_id: string;
      quantity: number;
      name: string;
      price: number;
    }>,
  ) => void;
  setQuantity: (lineId: string, quantity: number) => void;
  remove: (lineId: string) => void;
  clear: () => void;
}

const CartContext = createContext<CartValue | null>(null);

function readCart(): CartItem[] {
  try {
    const parsed = JSON.parse(
      localStorage.getItem(STORAGE_KEY) ?? "[]",
    ) as unknown;
    return Array.isArray(parsed) ? (parsed as CartItem[]) : [];
  } catch {
    return [];
  }
}

export function CartProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<CartItem[]>(readCart);
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
    } catch {
      // Embedded WebViews can disable storage; the current cart still works in memory.
    }
  }, [items]);
  const value = useMemo<CartValue>(
    () => ({
      items,
      count: items.reduce((sum, item) => sum + item.quantity, 0),
      add: (item, modifiers) =>
        setItems((current) => [
          ...current,
          {
            line_id: createIdempotencyKey(),
            menu_item_id: item.id,
            quantity: 1,
            modifiers: modifiers.map(({ option_id, quantity }) => ({
              option_id,
              quantity,
            })),
            name: item.name,
            image_url: item.image_url,
            unit_estimate_minor:
              item.price_minor +
              modifiers.reduce(
                (sum, modifier) => sum + modifier.price * modifier.quantity,
                0,
              ),
            modifier_names: modifiers.map((modifier) => modifier.name),
          },
        ]),
      setQuantity: (lineId, quantity) =>
        setItems((current) =>
          current.map((item) =>
            item.line_id === lineId
              ? { ...item, quantity: Math.max(1, Math.min(99, quantity)) }
              : item,
          ),
        ),
      remove: (lineId) =>
        setItems((current) =>
          current.filter((item) => item.line_id !== lineId),
        ),
      clear: () => setItems([]),
    }),
    [items],
  );
  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

export function useCart(): CartValue {
  const value = useContext(CartContext);
  if (!value) throw new Error("useCart must be used inside CartProvider");
  return value;
}

export function useOptionalCart(): CartValue | null {
  return useContext(CartContext);
}
