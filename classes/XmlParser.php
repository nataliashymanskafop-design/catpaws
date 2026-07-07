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
        $xml = simplexml_load_file($this->config['xml_url']);

        if ($xml === false) {
            throw new Exception('Не вдалося завантажити XML.');
        }

        // Horoshop може віддавати <shop><offers> або просто <offers>
        if (isset($xml->shop->offers->offer)) {
            $items = $xml->shop->offers->offer;
        } elseif (isset($xml->offers->offer)) {
            $items = $xml->offers->offer;
        } elseif (isset($xml->offer)) {
            $items = $xml->offer;
        } else {
            throw new Exception('Не знайдено товари у XML.');
        }

        $offers = [];

        foreach ($items as $item) {

            $offer = new Offer();

            $offer->code = trim((string)$item->vendorCode);

            $offer->price = (int)$item->price;

            $offer->oldPrice = !empty($item->oldprice)
                ? (int)$item->oldprice
                : null;

            $offer->available =
                ((string)$item['available'] === 'true');

            // Країна виробництва (якщо є в param)
            if (isset($item->param)) {
                foreach ($item->param as $param) {
                    $name = mb_strtolower((string)$param['name']);

                    if (str_contains($name, 'країна')) {
                        $offer->countryCode = trim((string)$param);
                        break;
                    }
                }
            }

            $offers[] = $offer;
        }

        return $offers;
    }
}
