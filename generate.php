<?php

declare(strict_types=1);

$config = require __DIR__ . '/config.php';

require_once __DIR__ . '/classes/Offer.php';
require_once __DIR__ . '/classes/XmlParser.php';
require_once __DIR__ . '/classes/FeedBuilder.php';

$parser = new XmlParser($config);

$offers = $parser->parse();

$builder = new FeedBuilder($config);

$json = $builder->build($offers);

file_put_contents(
    $config['cache_file'],
    $json,
    LOCK_EX
);

echo 'OK. Generated ' . count($offers) . ' offers.';
