ALTER TABLE site_payment_orders
ADD COLUMN IF NOT EXISTS product_id TEXT NOT NULL DEFAULT '';

ALTER TABLE site_payment_orders
ADD COLUMN IF NOT EXISTS offer_id TEXT NOT NULL DEFAULT '';

ALTER TABLE site_payment_orders
ADD COLUMN IF NOT EXISTS openid TEXT NOT NULL DEFAULT '';

ALTER TABLE site_payment_orders
ADD COLUMN IF NOT EXISTS environment INTEGER NOT NULL DEFAULT 0;

CREATE UNIQUE INDEX IF NOT EXISTS idx_site_payment_orders_transaction
ON site_payment_orders(transaction_id)
WHERE transaction_id <> '';
