<?php

declare(strict_types=1);

require_once __DIR__ . '/Offer.php';

class XmlParser
{
    private array $config;

    public function __construct(array $config)
    {
        $this->config = $config;
    }

    /**
     * @return Offer[]
     */
    public function parse(): array
    {
        $offers = [];

        $xml = simplexml_load_file($this->config['xml_url']);

        if (!$xml) {
            throw new Exception('Не вдалося завантажити XML.');
        }

        foreach ($xml->offers->offer as $item) {

            $offer = new Offer();

            $offer->code = trim((string)$item->vendorCode);

            $offer->price = (int)$item->price;

            $offer->oldPrice = isset($item->oldprice)
                ? (int)$item->oldprice
                : null;

            $offer->available =
                ((string)$item['available'] === 'true');

            $offers[] = $offer;
        }

        return $offers;
    }
}
