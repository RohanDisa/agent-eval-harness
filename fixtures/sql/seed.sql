DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS regions;

CREATE TABLE regions (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  continent TEXT NOT NULL
);

CREATE TABLE customers (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  region_id INTEGER NOT NULL,
  tier TEXT NOT NULL,
  FOREIGN KEY (region_id) REFERENCES regions(id)
);

CREATE TABLE products (
  id INTEGER PRIMARY KEY,
  sku TEXT NOT NULL,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  unit_price REAL NOT NULL
);

CREATE TABLE orders (
  id INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL,
  ordered_at TEXT NOT NULL,
  status TEXT NOT NULL,
  FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE order_items (
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  qty INTEGER NOT NULL,
  FOREIGN KEY (order_id) REFERENCES orders(id),
  FOREIGN KEY (product_id) REFERENCES products(id)
);

INSERT INTO regions (id, name, continent) VALUES
  (1, 'EMEA', 'Europe'),
  (2, 'NA', 'North America'),
  (3, 'APAC', 'Asia');

INSERT INTO customers (id, name, region_id, tier) VALUES
  (1, 'Aurora GmbH', 1, 'gold'),
  (2, 'Northwind LLC', 2, 'silver'),
  (3, 'Sakura KK', 3, 'gold'),
  (4, 'Consilium SA', 1, 'bronze'),
  (5, 'Cascade Inc', 2, 'gold');

INSERT INTO products (id, sku, name, category, unit_price) VALUES
  (1, 'WDG-1', 'Widget', 'hardware', 12.50),
  (2, 'GDG-2', 'Gadget', 'hardware', 40.00),
  (3, 'SVC-9', 'Support plan', 'service', 200.00),
  (4, 'CAB-4', 'Cable', 'hardware', 4.25),
  (5, 'LIC-7', 'License', 'software', 99.00);

INSERT INTO orders (id, customer_id, ordered_at, status) VALUES
  (1, 1, '2024-07-12', 'shipped'),
  (2, 1, '2024-08-03', 'shipped'),
  (3, 2, '2024-07-20', 'cancelled'),
  (4, 3, '2024-09-01', 'shipped'),
  (5, 5, '2024-08-18', 'shipped'),
  (6, 4, '2024-09-14', 'pending');

INSERT INTO order_items (id, order_id, product_id, qty) VALUES
  (1, 1, 1, 10),
  (2, 1, 4, 20),
  (3, 2, 3, 1),
  (4, 3, 2, 5),
  (5, 4, 5, 3),
  (6, 5, 2, 2),
  (7, 5, 1, 8),
  (8, 6, 4, 40);
